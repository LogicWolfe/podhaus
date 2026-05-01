#!/usr/bin/env python3
"""Classify RAR-backlog folders as EXTRACTED / NEVER_EXTRACTED / NEEDS_REVIEW.

Read-only. Takes folder paths on stdin (one per line — typically piped from
find-unhealthy.sh). For each folder:

  * find the primary RAR archive and run `unrar lt` to get expected output
    filename(s) + size(s);
  * run `unrar t` to check integrity;
  * search the folder's own subtree (recursive) and its immediate parent
    directory (non-recursive) for a video file matching each expected output
    by name + size (within 1%);
  * emit a classification.

Writes:
  * CSV at --output (default /state/rar-backlog-audit.csv)
  * Markdown summary at --summary (default /state/rar-backlog-audit.md)

Invocation (from host):
  ./find-unhealthy.sh | docker run --rm -i \\
      -v /mnt/pouch:/data:ro \\
      -v .../rar-cleanup-scripts:/scripts:ro,z \\
      -v .../podhaus-migration-state:/state:z \\
      rar-cleanup:local python3 /scripts/audit.py
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts"}
RAR_PART_RE = re.compile(r"\.part0*1\.rar$", re.IGNORECASE)
SIZE_TOLERANCE = 0.01  # 1%


@dataclass
class ArchiveEntry:
    name: str
    size: int


@dataclass
class Match:
    path: str
    size: int
    confidence: str  # high | medium | low


@dataclass
class Row:
    folder_path: str
    archive_expected_filename: str = ""
    archive_expected_size: int = 0
    match_path: str = ""
    match_size: int = 0
    match_confidence: str = ""
    classification: str = ""
    notes: str = ""


def find_primary_rar(folder: Path) -> Path | None:
    """Return the first volume of the multi-part RAR set in folder, or None."""
    try:
        entries = [e for e in folder.iterdir() if e.is_file()]
    except OSError:
        return None
    # Prefer partNN.rar scheme where NN == 1.
    part01 = [e for e in entries if RAR_PART_RE.search(e.name)]
    if part01:
        return sorted(part01)[0]
    # Otherwise, classic scheme: single .rar (first volume; rest are .r00..).
    bare_rar = [e for e in entries if e.suffix.lower() == ".rar"
                and not re.search(r"\.part\d+\.rar$", e.name, re.IGNORECASE)]
    if bare_rar:
        return sorted(bare_rar)[0]
    # Pack with multiple independent archives (each its own release):
    # fall through — caller will see None and mark NEEDS_REVIEW if appropriate.
    any_rar = [e for e in entries if e.suffix.lower() == ".rar"]
    if any_rar:
        return sorted(any_rar)[0]
    return None


def run_unrar(args: list[str], cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["unrar", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def unrar_list(archive: Path) -> list[ArchiveEntry] | None:
    """Parse `unrar lt` output; return entries for File items, or None on failure."""
    try:
        proc = run_unrar(["lt", "-p-", str(archive)])
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    entries: list[ArchiveEntry] = []
    current_name: str | None = None
    current_type: str | None = None
    current_size: int | None = None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            if current_name and current_type == "File" and current_size is not None:
                entries.append(ArchiveEntry(current_name, current_size))
            current_name = current_type = current_size = None
            continue
        if line.startswith("Name: "):
            current_name = line[len("Name: "):].strip()
        elif line.startswith("Type: "):
            current_type = line[len("Type: "):].strip()
        elif line.startswith("Size: "):
            try:
                current_size = int(line[len("Size: "):].strip())
            except ValueError:
                current_size = None
    if current_name and current_type == "File" and current_size is not None:
        entries.append(ArchiveEntry(current_name, current_size))
    return entries


def unrar_test(archive: Path) -> bool:
    try:
        proc = run_unrar(["t", "-p-", str(archive)], timeout=600)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def pick_primary_video(entries: list[ArchiveEntry]) -> ArchiveEntry | None:
    """Return the largest video-file entry from an archive listing, or None."""
    videos = [e for e in entries if Path(e.name).suffix.lower() in VIDEO_EXTS]
    if not videos:
        return None
    return max(videos, key=lambda e: e.size)


def size_matches(a: int, b: int) -> bool:
    if a == b:
        return True
    return abs(a - b) / max(a, b) <= SIZE_TOLERANCE


def collect_search_space(folder: Path) -> list[Path]:
    """Recursive walk of folder + non-recursive listing of folder's parent."""
    results: list[Path] = []
    for root, _dirs, files in os.walk(folder, followlinks=False):
        root_path = Path(root)
        for name in files:
            results.append(root_path / name)
    parent = folder.parent
    try:
        for entry in os.scandir(parent):
            if entry.is_file(follow_symlinks=False):
                results.append(Path(entry.path))
    except OSError:
        pass
    return results


def find_matches(expected_name: str, expected_size: int, candidates: list[Path]) -> list[Match]:
    """Return candidate files that match expected by name + size."""
    expected_basename = Path(expected_name).name.lower()
    expected_stem = Path(expected_basename).stem
    matches: list[Match] = []
    for path in candidates:
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if not size_matches(size, expected_size):
            continue
        cand_name = path.name.lower()
        cand_stem = path.stem.lower()
        if cand_name == expected_basename:
            confidence = "high" if size == expected_size else "medium"
        elif expected_stem and expected_stem in cand_stem:
            confidence = "medium" if size == expected_size else "low"
        elif cand_stem and cand_stem in expected_stem:
            confidence = "low"
        else:
            continue
        matches.append(Match(path=str(path), size=size, confidence=confidence))
    return matches


def classify_folder(folder: Path) -> Row:
    row = Row(folder_path=str(folder))
    archive = find_primary_rar(folder)
    if archive is None:
        row.classification = "NEEDS_REVIEW"
        row.notes = "no rar archive found in folder"
        return row

    entries = unrar_list(archive)
    if entries is None:
        row.classification = "NEEDS_REVIEW"
        row.notes = f"unrar l failed: {archive.name}"
        return row

    primary = pick_primary_video(entries)
    if primary is None:
        row.classification = "NEEDS_REVIEW"
        non_video = [e.name for e in entries[:3]]
        row.notes = f"no video in archive; contents sample: {non_video}"
        return row

    row.archive_expected_filename = primary.name
    row.archive_expected_size = primary.size

    candidates = collect_search_space(folder)
    matches = find_matches(primary.name, primary.size, candidates)

    if len(matches) == 1:
        m = matches[0]
        row.match_path = m.path
        row.match_size = m.size
        row.match_confidence = m.confidence
        row.classification = "EXTRACTED"
        return row
    if len(matches) > 1:
        best = max(matches, key=lambda m: (m.confidence == "high", m.confidence == "medium", m.size))
        row.match_path = best.path
        row.match_size = best.size
        row.match_confidence = best.confidence
        row.classification = "NEEDS_REVIEW"
        row.notes = f"multiple matches ({len(matches)}); showing best"
        return row

    # Zero matches. Integrity check to distinguish NEVER_EXTRACTED from CORRUPT.
    if not unrar_test(archive):
        row.classification = "NEEDS_REVIEW"
        row.notes = "unrar t failed (corrupt or incomplete)"
        return row

    row.classification = "NEVER_EXTRACTED"
    return row


def write_csv(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "folder_path",
        "archive_expected_filename",
        "archive_expected_size",
        "match_path",
        "match_size",
        "match_confidence",
        "classification",
        "notes",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: getattr(row, k) for k in fieldnames})


def write_summary(path: Path, rows: list[Row]) -> None:
    counts = Counter(r.classification for r in rows)
    total = len(rows)
    lines = ["# RAR backlog audit summary", ""]
    lines.append(f"Total folders audited: **{total}**")
    lines.append("")
    lines.append("## Counts by classification")
    lines.append("")
    lines.append("| classification | count |")
    lines.append("|---|---|")
    for cls in ("EXTRACTED", "NEVER_EXTRACTED", "NEEDS_REVIEW"):
        lines.append(f"| {cls} | {counts.get(cls, 0)} |")
    lines.append("")
    for cls in ("EXTRACTED", "NEVER_EXTRACTED", "NEEDS_REVIEW"):
        subset = [r for r in rows if r.classification == cls]
        lines.append(f"## {cls} — {len(subset)} folders")
        lines.append("")
        for r in subset[:10]:
            extra = f" → `{r.match_path}` ({r.match_confidence})" if r.match_path else ""
            note = f" — _{r.notes}_" if r.notes else ""
            lines.append(f"- `{r.folder_path}`{extra}{note}")
        if len(subset) > 10:
            lines.append(f"- …and {len(subset) - 10} more (see CSV)")
        lines.append("")
    # Note-frequency breakdown for NEEDS_REVIEW
    review = [r for r in rows if r.classification == "NEEDS_REVIEW"]
    if review:
        lines.append("## NEEDS_REVIEW note breakdown")
        lines.append("")
        note_bucket = Counter()
        for r in review:
            key = r.notes.split(";")[0].split(":")[0] if r.notes else "(no note)"
            note_bucket[key] += 1
        for note, count in note_bucket.most_common():
            lines.append(f"- {count}× {note}")
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--list", type=Path, help="Read folder paths from file (default: stdin).")
    p.add_argument("--limit", type=int, default=0, help="Process only first N folders.")
    p.add_argument("--output", type=Path, default=Path("/state/rar-backlog-audit.csv"))
    p.add_argument("--summary", type=Path, default=Path("/state/rar-backlog-audit.md"))
    args = p.parse_args()

    if args.list:
        folders_raw = args.list.read_text().splitlines()
    else:
        folders_raw = sys.stdin.read().splitlines()
    folders = [Path(f.strip()) for f in folders_raw if f.strip()]
    if args.limit > 0:
        folders = folders[: args.limit]

    n = len(folders)
    if n == 0:
        print("No folders to audit.", file=sys.stderr)
        return 0
    print(f"Auditing {n} folders → {args.output}", file=sys.stderr, flush=True)

    rows: list[Row] = []
    for i, folder in enumerate(folders, 1):
        row = classify_folder(folder)
        rows.append(row)
        suffix = ""
        if row.match_confidence:
            suffix = f" ({row.match_confidence})"
        elif row.notes:
            suffix = f" [{row.notes[:60]}]"
        print(f"[{i}/{n}] {row.classification}{suffix}  {folder}", flush=True)

    write_csv(args.output, rows)
    write_summary(args.summary, rows)
    counts = Counter(r.classification for r in rows)
    print(
        f"\nDone. EXTRACTED={counts.get('EXTRACTED', 0)} "
        f"NEVER_EXTRACTED={counts.get('NEVER_EXTRACTED', 0)} "
        f"NEEDS_REVIEW={counts.get('NEEDS_REVIEW', 0)}",
        flush=True,
    )
    print(f"CSV:     {args.output}", flush=True)
    print(f"Summary: {args.summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
