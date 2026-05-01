#!/usr/bin/env python3
"""Act on the audit CSV: delete RARs for EXTRACTED rows, extract+delete for NEVER_EXTRACTED.

DESTRUCTIVE. Always run with --dry-run first.

Invocation:
  docker run --rm \\
      -v /mnt/pouch:/data \\
      -v .../rar-cleanup-scripts:/scripts:ro,z \\
      -v .../podhaus-migration-state:/state:z \\
      rar-cleanup:local \\
      python3 /scripts/remediate.py --classification EXTRACTED --dry-run
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts"}
RAR_SUFFIX_RE = re.compile(r"^\.(rar|r\d{2})$", re.IGNORECASE)
RAR_PART_RE = re.compile(r"\.part\d+\.rar$", re.IGNORECASE)
SCENE_META_EXTS = {".sfv", ".srr", ".srs", ".nfo"}
SIZE_TOLERANCE = 0.01
ALLOWED_ROOTS = ("/data/Movies/", "/data/TV/", "/data/Kids/")
VALID_CLASSIFICATIONS = {"EXTRACTED", "NEVER_EXTRACTED", "NEEDS_REVIEW", "SKIP"}


@dataclass
class Row:
    folder_path: str
    archive_expected_filename: str
    archive_expected_size: int
    match_path: str
    match_size: int
    match_confidence: str
    classification: str
    notes: str


def read_csv(path: Path) -> list[Row]:
    with path.open() as f:
        reader = csv.DictReader(f)
        rows = []
        for raw in reader:
            rows.append(Row(
                folder_path=raw["folder_path"],
                archive_expected_filename=raw.get("archive_expected_filename", ""),
                archive_expected_size=int(raw.get("archive_expected_size") or 0),
                match_path=raw.get("match_path", ""),
                match_size=int(raw.get("match_size") or 0),
                match_confidence=raw.get("match_confidence", ""),
                classification=raw.get("classification", "").strip().upper(),
                notes=raw.get("notes", ""),
            ))
    return rows


def open_sidecar(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            folder_path     TEXT PRIMARY KEY,
            classification  TEXT NOT NULL,
            action          TEXT NOT NULL,
            outcome         TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            notes           TEXT
        )
    """)
    conn.commit()
    return conn


def already_completed(conn: sqlite3.Connection, folder: str) -> bool:
    cur = conn.execute("SELECT outcome FROM actions WHERE folder_path = ?", (folder,))
    row = cur.fetchone()
    return row is not None and row[0] == "ok"


def record_start(conn: sqlite3.Connection, folder: str, cls: str, action: str) -> None:
    conn.execute("""
        INSERT INTO actions(folder_path, classification, action, outcome, started_at)
        VALUES(?, ?, ?, 'in_progress', datetime('now'))
        ON CONFLICT(folder_path) DO UPDATE SET
            classification=excluded.classification,
            action=excluded.action,
            outcome='in_progress',
            started_at=datetime('now'),
            finished_at=NULL,
            notes=NULL
    """, (folder, cls, action))
    conn.commit()


def record_finish(conn: sqlite3.Connection, folder: str, outcome: str, notes: str = "") -> None:
    conn.execute("""
        UPDATE actions SET outcome=?, finished_at=datetime('now'), notes=?
        WHERE folder_path=?
    """, (outcome, notes, folder))
    conn.commit()


def path_allowed(folder: Path) -> bool:
    s = str(folder)
    return any(s.startswith(r) for r in ALLOWED_ROOTS)


def size_matches(a: int, b: int) -> bool:
    if a == b:
        return True
    return abs(a - b) / max(a, b) <= SIZE_TOLERANCE


def collect_rar_pieces(folder: Path) -> list[Path]:
    result: list[Path] = []
    try:
        for entry in folder.rglob("*"):
            if not entry.is_file():
                continue
            name = entry.name
            suffix = entry.suffix
            if RAR_SUFFIX_RE.match(suffix) or RAR_PART_RE.search(name):
                result.append(entry)
    except OSError:
        pass
    return result


def collect_scene_meta(folder: Path) -> list[Path]:
    result: list[Path] = []
    try:
        for entry in folder.rglob("*"):
            if entry.is_file() and entry.suffix.lower() in SCENE_META_EXTS:
                result.append(entry)
    except OSError:
        pass
    return result


def collect_sample_dirs(folder: Path) -> list[Path]:
    result: list[Path] = []
    try:
        for entry in folder.rglob("*"):
            if entry.is_dir() and entry.name.lower() in ("sample", "proof"):
                result.append(entry)
    except OSError:
        pass
    return result


def collect_sample_videos(folder: Path) -> list[Path]:
    result: list[Path] = []
    # "top 2 levels" matches rtorrent-cleanup.sh -maxdepth 2
    for depth_prefix in ("*", "*/*"):
        for cand in folder.glob(depth_prefix):
            if not cand.is_file():
                continue
            if "sample" in cand.name.lower() and cand.suffix.lower() in VIDEO_EXTS:
                result.append(cand)
    return result


def collect_empty_subdirs(folder: Path) -> list[Path]:
    result: list[Path] = []
    try:
        for entry in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if entry.is_dir() and entry != folder:
                try:
                    if not any(entry.iterdir()):
                        result.append(entry)
                except OSError:
                    pass
    except OSError:
        pass
    return result


def find_primary_rar(folder: Path) -> Path | None:
    try:
        entries = [e for e in folder.iterdir() if e.is_file()]
    except OSError:
        return None
    part01 = [e for e in entries if re.search(r"\.part0*1\.rar$", e.name, re.IGNORECASE)]
    if part01:
        return sorted(part01)[0]
    bare_rar = [e for e in entries if e.suffix.lower() == ".rar"
                and not re.search(r"\.part\d+\.rar$", e.name, re.IGNORECASE)]
    if bare_rar:
        return sorted(bare_rar)[0]
    any_rar = [e for e in entries if e.suffix.lower() == ".rar"]
    if any_rar:
        return sorted(any_rar)[0]
    return None


def verify_match(row: Row) -> tuple[bool, str]:
    p = Path(row.match_path)
    if not p.is_file():
        return False, f"match_path no longer exists: {row.match_path}"
    actual_size = p.stat().st_size
    # Prefer match_size when the CSV has one (it's what was audited or
    # hand-curated for this row); fall back to archive_expected_size for
    # auto-discovered EXTRACTED rows where match_size mirrors it anyway.
    expected = row.match_size if row.match_size > 0 else row.archive_expected_size
    if expected <= 0:
        return True, ""
    if not size_matches(actual_size, expected):
        return False, (
            f"size drift: match_path={actual_size}, expected={expected}"
        )
    return True, ""


def plan_deletions(folder: Path) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    return (
        collect_rar_pieces(folder),
        collect_scene_meta(folder),
        collect_sample_dirs(folder),
        collect_sample_videos(folder),
    )


def do_delete(paths_files: list[Path], paths_dirs: list[Path]) -> None:
    for p in paths_files:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    for d in paths_dirs:
        shutil.rmtree(d, ignore_errors=True)


def remove_empty_subdirs(folder: Path) -> int:
    n = 0
    for d in collect_empty_subdirs(folder):
        try:
            d.rmdir()
            n += 1
        except OSError:
            pass
    return n


def handle_extracted(row: Row, folder: Path, dry_run: bool) -> tuple[str, str]:
    ok, msg = verify_match(row)
    if not ok:
        return "error", msg
    rars, metas, sample_dirs, sample_vids = plan_deletions(folder)
    summary = (
        f"delete: {len(rars)} rar pieces, {len(metas)} scene-meta, "
        f"{len(sample_dirs)} sample dirs, {len(sample_vids)} sample videos"
    )
    if dry_run:
        print(f"    DRY-RUN: {summary}", flush=True)
        if rars[:2]:
            print(f"    e.g. {rars[0].name}", flush=True)
        return "dry_run", summary
    do_delete(rars + metas + sample_vids, sample_dirs)
    removed = remove_empty_subdirs(folder)
    return "ok", f"{summary}; removed {removed} empty subdirs"


def handle_never_extracted(row: Row, folder: Path, dry_run: bool) -> tuple[str, str]:
    archive = find_primary_rar(folder)
    if archive is None:
        return "error", "no primary rar found at remediation time"
    expected_name = row.archive_expected_filename
    expected_size = row.archive_expected_size
    if not expected_name or expected_size <= 0:
        return "error", "csv missing archive_expected_filename/size for NEVER_EXTRACTED row"
    target = folder / expected_name
    if target.exists():
        return "error", f"target file already exists, refusing overwrite: {target}"
    if dry_run:
        print(f"    DRY-RUN: unrar x -> {target.name}, then delete {len(collect_rar_pieces(folder))} rar + scene meta", flush=True)
        return "dry_run", f"would extract {archive.name} → {expected_name}, then delete"
    failure: str | None = None
    try:
        proc = subprocess.run(
            ["unrar", "x", "-o-", "-p-", str(archive)],
            cwd=str(folder),
            capture_output=True,
            text=True,
            timeout=7200,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        failure = f"unrar x failed: {e}"
    else:
        if proc.returncode != 0:
            tail = (proc.stdout[-300:] + proc.stderr[-300:]).strip()
            failure = f"unrar x exit {proc.returncode}: {tail}"
        elif not target.is_file():
            failure = f"expected output missing after extract: {target}"
        else:
            actual = target.stat().st_size
            if not size_matches(actual, expected_size):
                failure = f"extracted size drift: {actual} vs expected {expected_size}"

    if failure is not None:
        # Extraction failed. Per user direction: give up on this content
        # and clean up the folder anyway — remove any partial output, then
        # delete the RAR pieces + scene metadata so the folder stops failing
        # the rar-backlog health check. The archive was already broken
        # (unrar t said so or the write stream died mid-stream).
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass
        rars, metas, sample_dirs, sample_vids = plan_deletions(folder)
        do_delete(rars + metas + sample_vids, sample_dirs)
        removed = remove_empty_subdirs(folder)
        return "extract_failed_cleaned", (
            f"{failure}; cleaned up: deleted {len(rars)} rars + {len(metas)} meta + "
            f"{len(sample_dirs)} sample dirs + {len(sample_vids)} sample vids; "
            f"removed {removed} empty subdirs"
        )

    actual = target.stat().st_size
    rars, metas, sample_dirs, sample_vids = plan_deletions(folder)
    do_delete(rars + metas + sample_vids, sample_dirs)
    removed = remove_empty_subdirs(folder)
    return "ok", (
        f"extracted {archive.name} ({actual} bytes); deleted {len(rars)} rars + "
        f"{len(metas)} meta + {len(sample_dirs)} sample dirs + {len(sample_vids)} sample vids; "
        f"removed {removed} empty subdirs"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=Path("/state/rar-backlog-audit.csv"))
    p.add_argument("--sidecar", type=Path, default=Path("/state/rar-backlog-remediation.sqlite"))
    p.add_argument("--dry-run", action="store_true", help="Plan only; touch nothing.")
    p.add_argument("--limit", type=int, default=0, help="Process first N rows then exit.")
    p.add_argument("--classification", choices=sorted(VALID_CLASSIFICATIONS),
                   help="Only process rows with this classification.")
    p.add_argument("--resume", action="store_true",
                   help="Skip rows already recorded as outcome='ok' in the sidecar.")
    args = p.parse_args()

    rows = read_csv(args.csv)
    if args.classification:
        rows = [r for r in rows if r.classification == args.classification]
    if args.limit > 0:
        rows = rows[: args.limit]

    if not rows:
        print("No rows to process.", flush=True)
        return 0

    print(
        f"Plan: {len(rows)} rows"
        f"{' (DRY-RUN)' if args.dry_run else ''}"
        f"{' [' + args.classification + ']' if args.classification else ''}",
        flush=True,
    )

    with closing(open_sidecar(args.sidecar)) as conn:
        outcomes: Counter[str] = Counter()
        n = len(rows)
        for i, row in enumerate(rows, 1):
            folder = Path(row.folder_path)
            tag = f"[{i}/{n}] {row.classification}  {folder}"
            print(tag, flush=True)

            if row.classification not in ("EXTRACTED", "NEVER_EXTRACTED"):
                print(f"    skip ({row.classification})", flush=True)
                outcomes["skipped"] += 1
                continue

            if not path_allowed(folder):
                print(f"    ERROR: path outside /data/{{Movies,TV,Kids}}: {folder}", flush=True)
                outcomes["error"] += 1
                continue

            if not folder.is_dir():
                print(f"    ERROR: folder does not exist: {folder}", flush=True)
                outcomes["error"] += 1
                continue

            if args.resume and already_completed(conn, str(folder)):
                print(f"    resume: already completed", flush=True)
                outcomes["resumed"] += 1
                continue

            action = "delete" if row.classification == "EXTRACTED" else "extract+delete"
            if not args.dry_run:
                record_start(conn, str(folder), row.classification, action)

            t0 = time.monotonic()
            if row.classification == "EXTRACTED":
                outcome, detail = handle_extracted(row, folder, args.dry_run)
            else:
                outcome, detail = handle_never_extracted(row, folder, args.dry_run)
            elapsed = time.monotonic() - t0

            print(f"    {outcome} ({elapsed:.1f}s): {detail}", flush=True)
            outcomes[outcome] += 1
            if not args.dry_run:
                record_finish(conn, str(folder), outcome, detail)

    print("", flush=True)
    print("Summary:", flush=True)
    for k, v in sorted(outcomes.items()):
        print(f"  {k}: {v}", flush=True)
    return 0 if outcomes.get("error", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
