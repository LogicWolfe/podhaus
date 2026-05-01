#!/usr/bin/env python3
"""Build a SQLite database of per-file video quality measurements.

Runs three passes per file and records what we measured. Does not
classify or judge — bucketing is left to downstream queries because
it's a policy decision (where do you draw the line between
"watchable" and "incomplete"?), and we don't want to re-run hours of
analysis to change a threshold.

Passes per file:

  1. Header probe (ffprobe -show_format -show_streams)
       container format, declared duration & bitrate, video/audio
       codec, resolution, fps.

  2. Demux pass (ffmpeg -c copy -f null -progress pipe:1)
       last successful out_time → demux_decoded_s; demux ratio is
       decoded/declared. Stderr is parsed for error events; each
       distinct error gets a row in the `errors` table with byte
       offset (when ffmpeg prints one), an approximate timestamp
       (offset / file_size × declared_duration), kind, message.

  3. Video packet PTS pass (ffprobe -show_packets -select_streams v:0)
       walks all video packet pts. Computes consecutive deltas;
       anything > 2× median is a gap, the excess is lost time. Sums
       across all gaps → measured_lost_s. This is the only pass that
       catches mid-file holes that ffmpeg silently demuxes through.

Optional fourth pass (--count-frames): full decode to count frames.
Slow (real-time-ish per file) but gives ground-truth deficit.

Schema:

  files       one row per video file, with all metadata + summary
              measurements (durations, ratios, error_count, gap totals)
  errors      one row per distinct corruption event, FK to files.path
  runs        one row per analyzer invocation (when, mode, args)

Input: paths from stdin or --paths-file, one per line.
Output: SQLite DB at --db (default /tmp/plex-quality.db).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEMUX_TIMEOUT = 600
PACKET_TIMEOUT = 1800
COUNT_FRAMES_TIMEOUT = 1800

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".mpg", ".mpeg", ".webm"}

PROGRESS_RE = re.compile(r"out_time_us=(\d+)")
OFFSET_RE = re.compile(r"offset 0x([0-9a-fA-F]+)|pos[:= ]\s*(\d+)")
KIND_PATTERNS = [
    ("invalid_data",      re.compile(r"Invalid data found", re.I)),
    ("truncated_packet",  re.compile(r"[Tt]runcated", re.I)),
    ("non_monotonic_dts", re.compile(r"non monotonic", re.I)),
    ("ebml_corruption",   re.compile(r"EBML|matroska|webm", re.I)),
    ("nal_corruption",    re.compile(r"NAL", re.I)),
    ("moov_missing",      re.compile(r"moov atom not found", re.I)),
    ("decode_error",      re.compile(r"error while decoding", re.I)),
    ("missing_picture",   re.compile(r"missing picture", re.I)),
]

SHOW_RE = re.compile(r"/TV/([^/]+)/")
SE_RE = re.compile(
    r"[Ss](\d{1,2})[\s._-]*[Ee](\d{1,3})"
    r"|(\d{1,2})x(\d{1,3})"
    r"|[Ss]eason[\s_]*(\d{1,2}).*[Ee]pisode[\s_]*(\d{1,3})"
)


@dataclass
class ErrorEvent:
    seq: int
    byte_offset: int | None
    time_s: float | None
    time_pct: float | None
    kind: str
    message: str


@dataclass
class FileMeasurement:
    path: str
    file_size_bytes: int
    file_mtime: str
    ext: str

    show: str | None = None
    season: int | None = None
    episode: int | None = None

    container_format: str | None = None
    declared_duration_s: float | None = None
    declared_bitrate: int | None = None
    video_codec: str | None = None
    video_width: int | None = None
    video_height: int | None = None
    video_fps: float | None = None
    audio_codec: str | None = None

    demux_decoded_s: float | None = None
    demux_ratio: float | None = None
    demux_exit_code: int | None = None

    error_count: int = 0
    first_error_offset: int | None = None
    first_error_time_s: float | None = None
    first_error_time_pct: float | None = None
    last_error_offset: int | None = None
    last_error_time_s: float | None = None
    last_error_time_pct: float | None = None
    error_span_pct: float | None = None

    gap_count: int = 0
    gap_total_s: float | None = None
    gap_median_s: float | None = None
    gap_max_s: float | None = None

    expected_frames: int | None = None
    actual_frames: int | None = None
    frame_deficit: int | None = None
    frame_deficit_pct: float | None = None

    analyzed_at: str = ""
    analyzer_mode: str = ""
    elapsed_s: float = 0.0

    errors: list[ErrorEvent] = field(default_factory=list)


def walk_video_files(roots: list[Path]):
    for root in roots:
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if name.startswith("._"):
                    continue
                if Path(name).suffix.lower() in VIDEO_EXTS:
                    yield os.path.join(dirpath, name)


def parse_show_episode(path: str) -> tuple[str | None, int | None, int | None]:
    show = None
    m = SHOW_RE.search(path)
    if m:
        show = m.group(1)
    name = Path(path).name
    m = SE_RE.search(name)
    if m:
        groups = [g for g in m.groups() if g is not None]
        if len(groups) >= 2:
            try:
                return show, int(groups[0]), int(groups[1])
            except ValueError:
                pass
    return show, None, None


def classify_error(msg: str) -> str:
    for kind, pat in KIND_PATTERNS:
        if pat.search(msg):
            return kind
    return "other"


def header_probe(path: str) -> dict:
    try:
        cp = subprocess.run(
            ["ffprobe", "-v", "error", "-of", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired:
        return {}
    if cp.returncode != 0:
        return {}
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        return {}


def apply_header(m: FileMeasurement, info: dict) -> None:
    fmt = info.get("format") or {}
    m.container_format = fmt.get("format_name")
    try:
        m.declared_duration_s = float(fmt.get("duration", 0)) or None
    except (TypeError, ValueError):
        m.declared_duration_s = None
    try:
        m.declared_bitrate = int(fmt.get("bit_rate", 0)) or None
    except (TypeError, ValueError):
        m.declared_bitrate = None
    streams = info.get("streams") or []
    for s in streams:
        if s.get("codec_type") == "video" and m.video_codec is None:
            m.video_codec = s.get("codec_name")
            m.video_width = s.get("width")
            m.video_height = s.get("height")
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
            try:
                num, den = fr.split("/")
                m.video_fps = float(num) / float(den) if float(den) else None
            except (ValueError, ZeroDivisionError):
                m.video_fps = None
        elif s.get("codec_type") == "audio" and m.audio_codec is None:
            m.audio_codec = s.get("codec_name")


def demux_pass(m: FileMeasurement) -> None:
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", m.path, "-c", "copy",
         "-f", "null", "-progress", "pipe:1", "-nostats", "-y", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    last_us = 0
    try:
        for line in proc.stdout:
            mp_ = PROGRESS_RE.search(line)
            if mp_:
                try:
                    last_us = max(last_us, int(mp_.group(1)))
                except ValueError:
                    pass
        proc.wait(timeout=DEMUX_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    m.demux_decoded_s = last_us / 1_000_000
    m.demux_exit_code = proc.returncode
    if m.declared_duration_s and m.declared_duration_s > 0:
        m.demux_ratio = m.demux_decoded_s / m.declared_duration_s

    err_text = (proc.stderr.read() or "").strip()
    seen_offsets: set[int] = set()
    seq = 0
    for line in err_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if any(skip in line for skip in ("Press [q]", "frame=", "Stream mapping", "Output #", "Input #")):
            continue
        offset = None
        om = OFFSET_RE.search(line)
        if om:
            try:
                offset = int(om.group(1), 16) if om.group(1) else int(om.group(2))
            except (ValueError, TypeError):
                offset = None
        # dedupe by offset where we have one
        if offset is not None and offset in seen_offsets:
            continue
        if offset is not None:
            seen_offsets.add(offset)
        time_s = None
        time_pct = None
        if offset is not None and m.file_size_bytes and m.declared_duration_s:
            time_pct = offset / m.file_size_bytes
            time_s = time_pct * m.declared_duration_s
        seq += 1
        m.errors.append(ErrorEvent(
            seq=seq,
            byte_offset=offset,
            time_s=time_s,
            time_pct=time_pct * 100 if time_pct is not None else None,
            kind=classify_error(line),
            message=line[:500],
        ))
    m.error_count = len(m.errors)
    located = [e for e in m.errors if e.time_s is not None]
    if located:
        first = min(located, key=lambda e: e.time_s)  # type: ignore[arg-type]
        last = max(located, key=lambda e: e.time_s)  # type: ignore[arg-type]
        m.first_error_offset = first.byte_offset
        m.first_error_time_s = first.time_s
        m.first_error_time_pct = first.time_pct
        m.last_error_offset = last.byte_offset
        m.last_error_time_s = last.time_s
        m.last_error_time_pct = last.time_pct
        if first.time_pct is not None and last.time_pct is not None:
            m.error_span_pct = last.time_pct - first.time_pct


GAP_MIN_SECONDS = 0.5      # ignore anything shorter than this — covers normal
                           # frame jitter and AVI dual-audio interleaving noise
GAP_MIN_MULTIPLE = 5       # also require at least 5x median frame interval, so
                           # high-fps content doesn't get a free pass


def packet_pts_pass(m: FileMeasurement) -> None:
    """Read every video packet's pts. Sets:
      - demux_decoded_s = max(pts) (effective duration from packets)
      - demux_ratio = decoded / declared
      - gap_count, gap_total_s, gap_median_s, gap_max_s

    A "gap" is a packet-to-packet interval significantly larger than
    the median frame interval AND above an absolute floor. Frame
    jitter, AVI's coarse 100ms timestamp resolution, and dual-audio
    interleaving all produce small variations that we don't want to
    flag as content loss."""
    try:
        cp = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time",
             "-of", "csv=p=0", m.path],
            capture_output=True, text=True, timeout=PACKET_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        m.demux_exit_code = -1
        m.errors.append(ErrorEvent(
            seq=1, byte_offset=None, time_s=None, time_pct=None,
            kind="packet_pts_timeout",
            message=f"ffprobe packet pass timed out after {PACKET_TIMEOUT}s",
        ))
        m.error_count = 1
        return
    m.demux_exit_code = cp.returncode
    pts: list[float] = []
    for ln in cp.stdout.splitlines():
        ln = ln.strip().rstrip(",")
        if not ln or ln == "N/A":
            continue
        try:
            pts.append(float(ln))
        except ValueError:
            continue
    if not pts:
        return
    pts.sort()
    m.demux_decoded_s = pts[-1]
    if m.declared_duration_s and m.declared_duration_s > 0:
        m.demux_ratio = m.demux_decoded_s / m.declared_duration_s
    if len(pts) < 3:
        return
    deltas = [b - a for a, b in zip(pts, pts[1:]) if b > a]
    if not deltas:
        return
    median_delta = statistics.median(deltas)
    if median_delta <= 0:
        return
    threshold = max(median_delta * GAP_MIN_MULTIPLE, GAP_MIN_SECONDS)
    gaps = [d - median_delta for d in deltas if d > threshold]
    m.gap_count = len(gaps)
    m.gap_total_s = sum(gaps) if gaps else 0.0
    m.gap_median_s = statistics.median(gaps) if gaps else 0.0
    m.gap_max_s = max(gaps) if gaps else 0.0


def count_frames_pass(m: FileMeasurement) -> None:
    try:
        cp = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-count_frames", "-show_entries", "stream=nb_read_frames",
             "-of", "default=noprint_wrappers=1:nokey=1", m.path],
            capture_output=True, text=True, timeout=COUNT_FRAMES_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired:
        return
    if cp.returncode != 0:
        return
    try:
        m.actual_frames = int(cp.stdout.strip())
    except ValueError:
        return
    if m.declared_duration_s and m.video_fps:
        m.expected_frames = int(round(m.declared_duration_s * m.video_fps))
        m.frame_deficit = m.expected_frames - m.actual_frames
        if m.expected_frames > 0:
            m.frame_deficit_pct = (m.frame_deficit / m.expected_frames) * 100


def analyze(args: tuple[str, str, bool, bool]) -> FileMeasurement:
    path, mode, full_demux, deep_frames = args
    t0 = time.monotonic()
    m = FileMeasurement(
        path=path,
        file_size_bytes=0,
        file_mtime="",
        ext=Path(path).suffix.lower().lstrip("."),
    )
    try:
        st = os.stat(path)
        m.file_size_bytes = st.st_size
        m.file_mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    except FileNotFoundError:
        m.elapsed_s = time.monotonic() - t0
        m.analyzer_mode = mode
        return m

    show, season, episode = parse_show_episode(path)
    m.show = show
    m.season = season
    m.episode = episode

    try:
        info = header_probe(path)
        apply_header(m, info)

        packet_pts_pass(m)
        if full_demux:
            demux_pass(m)
        if deep_frames:
            count_frames_pass(m)
    except Exception as e:  # pragma: no cover - defensive
        m.errors.append(ErrorEvent(
            seq=len(m.errors) + 1, byte_offset=None, time_s=None, time_pct=None,
            kind="analyze_exception",
            message=f"{type(e).__name__}: {e}"[:500],
        ))
        m.error_count = len(m.errors)

    m.analyzed_at = datetime.now(tz=timezone.utc).isoformat()
    m.analyzer_mode = mode
    m.elapsed_s = time.monotonic() - t0
    return m


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript("""
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS runs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at      TEXT NOT NULL,
        finished_at     TEXT,
        mode            TEXT NOT NULL,
        argv            TEXT NOT NULL,
        path_count      INTEGER NOT NULL DEFAULT 0,
        skipped_count   INTEGER NOT NULL DEFAULT 0
    );

    -- Each (path, run_id) is one row. History is preserved across runs;
    -- the latest measurement per path is the one with the largest id.
    CREATE TABLE IF NOT EXISTS measurements (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id                  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        path                    TEXT NOT NULL,
        show                    TEXT,
        season                  INTEGER,
        episode                 INTEGER,
        file_size_bytes         INTEGER,
        file_mtime              TEXT,
        ext                     TEXT,

        container_format        TEXT,
        declared_duration_s     REAL,
        declared_bitrate        INTEGER,
        video_codec             TEXT,
        video_width             INTEGER,
        video_height            INTEGER,
        video_fps               REAL,
        audio_codec             TEXT,

        demux_decoded_s         REAL,
        demux_ratio             REAL,
        demux_exit_code         INTEGER,

        error_count             INTEGER NOT NULL DEFAULT 0,
        first_error_offset      INTEGER,
        first_error_time_s      REAL,
        first_error_time_pct    REAL,
        last_error_offset       INTEGER,
        last_error_time_s       REAL,
        last_error_time_pct     REAL,
        error_span_pct          REAL,

        gap_count               INTEGER NOT NULL DEFAULT 0,
        gap_total_s             REAL,
        gap_median_s            REAL,
        gap_max_s               REAL,

        expected_frames         INTEGER,
        actual_frames           INTEGER,
        frame_deficit           INTEGER,
        frame_deficit_pct       REAL,

        analyzed_at             TEXT,
        analyzer_mode           TEXT,
        elapsed_s               REAL,
        UNIQUE(run_id, path)
    );

    CREATE TABLE IF NOT EXISTS errors (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        measurement_id  INTEGER NOT NULL REFERENCES measurements(id) ON DELETE CASCADE,
        seq             INTEGER NOT NULL,
        byte_offset     INTEGER,
        time_s          REAL,
        time_pct        REAL,
        kind            TEXT,
        message         TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_measurements_path ON measurements(path);
    CREATE INDEX IF NOT EXISTS idx_measurements_show ON measurements(show);
    CREATE INDEX IF NOT EXISTS idx_measurements_demux_ratio ON measurements(demux_ratio);
    CREATE INDEX IF NOT EXISTS idx_measurements_error_count ON measurements(error_count);
    CREATE INDEX IF NOT EXISTS idx_measurements_gap_total_s ON measurements(gap_total_s);
    CREATE INDEX IF NOT EXISTS idx_errors_measurement ON errors(measurement_id);

    -- Convenience view: latest measurement per path.
    CREATE VIEW IF NOT EXISTS latest_measurements AS
    SELECT m.* FROM measurements m
    INNER JOIN (
        SELECT path, MAX(id) AS max_id FROM measurements GROUP BY path
    ) lm ON m.id = lm.max_id;
    """)
    con.commit()
    return con


def fingerprint_seen(con: sqlite3.Connection, path: str,
                     size: int, mtime: str) -> bool:
    """True if any prior measurement matches this path's current size+mtime."""
    row = con.execute(
        "SELECT 1 FROM measurements WHERE path = ? "
        "AND file_size_bytes = ? AND file_mtime = ? LIMIT 1",
        (path, size, mtime),
    ).fetchone()
    return row is not None


def insert_measurement(con: sqlite3.Connection, m: FileMeasurement,
                       run_id: int) -> int:
    cur = con.execute(
        """
        INSERT INTO measurements (
            run_id, path, show, season, episode,
            file_size_bytes, file_mtime, ext,
            container_format, declared_duration_s, declared_bitrate,
            video_codec, video_width, video_height, video_fps, audio_codec,
            demux_decoded_s, demux_ratio, demux_exit_code,
            error_count,
            first_error_offset, first_error_time_s, first_error_time_pct,
            last_error_offset, last_error_time_s, last_error_time_pct,
            error_span_pct,
            gap_count, gap_total_s, gap_median_s, gap_max_s,
            expected_frames, actual_frames, frame_deficit, frame_deficit_pct,
            analyzed_at, analyzer_mode, elapsed_s
        ) VALUES (
            :run_id, :path, :show, :season, :episode,
            :file_size_bytes, :file_mtime, :ext,
            :container_format, :declared_duration_s, :declared_bitrate,
            :video_codec, :video_width, :video_height, :video_fps, :audio_codec,
            :demux_decoded_s, :demux_ratio, :demux_exit_code,
            :error_count,
            :first_error_offset, :first_error_time_s, :first_error_time_pct,
            :last_error_offset, :last_error_time_s, :last_error_time_pct,
            :error_span_pct,
            :gap_count, :gap_total_s, :gap_median_s, :gap_max_s,
            :expected_frames, :actual_frames, :frame_deficit, :frame_deficit_pct,
            :analyzed_at, :analyzer_mode, :elapsed_s
        )
        """,
        {**{k: getattr(m, k) for k in (
            "path", "show", "season", "episode",
            "file_size_bytes", "file_mtime", "ext",
            "container_format", "declared_duration_s", "declared_bitrate",
            "video_codec", "video_width", "video_height", "video_fps", "audio_codec",
            "demux_decoded_s", "demux_ratio", "demux_exit_code",
            "error_count",
            "first_error_offset", "first_error_time_s", "first_error_time_pct",
            "last_error_offset", "last_error_time_s", "last_error_time_pct",
            "error_span_pct",
            "gap_count", "gap_total_s", "gap_median_s", "gap_max_s",
            "expected_frames", "actual_frames", "frame_deficit", "frame_deficit_pct",
            "analyzed_at", "analyzer_mode", "elapsed_s",
        )}, "run_id": run_id},
    )
    measurement_id = cur.lastrowid
    con.executemany(
        """
        INSERT INTO errors (measurement_id, seq, byte_offset, time_s, time_pct, kind, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(measurement_id, e.seq, e.byte_offset, e.time_s, e.time_pct, e.kind, e.message)
         for e in m.errors],
    )
    return measurement_id


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--db", type=Path, default=Path("/tmp/plex-quality.db"))
    p.add_argument("--paths-file", type=Path,
                   help="read paths from this file, one per line")
    p.add_argument("--root", type=Path, action="append", default=[],
                   help="walk this directory for video files (repeatable)")
    p.add_argument("--full-demux", action="store_true",
                   help="add a full-file demux pass that captures ffmpeg stderr "
                        "errors (byte offsets, kinds). Slow — full file streamed "
                        "through ffmpeg. Default uses packet-PTS only.")
    p.add_argument("--count-frames", action="store_true",
                   help="add a slow ffprobe -count_frames pass per file")
    p.add_argument("--force", action="store_true",
                   help="re-analyze even if a prior measurement matches the file's "
                        "current size+mtime (default: skip unchanged files)")
    args = p.parse_args()

    if args.paths_file:
        paths = [ln.strip() for ln in args.paths_file.read_text().splitlines() if ln.strip()]
    elif args.root:
        paths = list(walk_video_files(args.root))
    else:
        paths = [ln.strip() for ln in sys.stdin if ln.strip()]
    paths = [p for p in paths if "/._" not in p]  # strip macOS dotfiles

    mode = "pts" + ("+demux" if args.full_demux else "") + ("+frames" if args.count_frames else "")
    con = init_db(args.db)
    cur = con.execute(
        "INSERT INTO runs (started_at, mode, argv, path_count) VALUES (?, ?, ?, ?)",
        (datetime.now(tz=timezone.utc).isoformat(), mode, " ".join(sys.argv), len(paths)),
    )
    run_id = cur.lastrowid
    con.commit()

    todo: list[str] = []
    skipped = 0
    for path in paths:
        if args.force:
            todo.append(path)
            continue
        try:
            st = os.stat(path)
        except FileNotFoundError:
            todo.append(path)
            continue
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        if fingerprint_seen(con, path, st.st_size, mtime):
            skipped += 1
        else:
            todo.append(path)
    if skipped:
        print(f"Skipping {skipped} unchanged files (use --force to re-analyze)", flush=True)
    print(f"Analyzing {len(todo)} files with {args.workers} workers (mode={mode}) → {args.db}", flush=True)

    work = [(pth, mode, args.full_demux, args.count_frames) for pth in todo]
    t_start = time.monotonic()
    with mp.Pool(args.workers) as pool:
        for i, m in enumerate(pool.imap_unordered(analyze, work, chunksize=1), 1):
            insert_measurement(con, m, run_id)
            con.commit()
            ratio_str = f"{m.demux_ratio:.3f}" if m.demux_ratio is not None else "N/A"
            print(
                f"  [{i}/{len(todo)}] errs={m.error_count} gaps={m.gap_count} "
                f"ratio={ratio_str} — {Path(m.path).name}",
                flush=True,
            )
            if i % 50 == 0:
                rate = i / (time.monotonic() - t_start)
                eta = (len(todo) - i) / rate if rate > 0 else 0
                print(f"  progress: {i}/{len(todo)}, {rate:.1f} files/s, ETA {eta/60:.1f} min", flush=True)

    con.execute(
        "UPDATE runs SET finished_at = ?, skipped_count = ? WHERE id = ?",
        (datetime.now(tz=timezone.utc).isoformat(), skipped, run_id),
    )
    con.commit()
    con.close()
    print(f"\nDone. Analyzed {len(todo)}, skipped {skipped}. DB: {args.db}", flush=True)


if __name__ == "__main__":
    main()
