#!/bin/sh
# Called by rtorrent's event.download.finished hook with $d.base_path= as $1.
#
# Real-time in-place RAR extraction for completed torrents. Replaces the
# previous unpackerr stack: rtorrent already knows the exact base_path
# each torrent landed under, so we walk that subtree at any depth for
# the archive entry-point, run bsdtar against it in place, and drop a
# `_unpackerred.<dir>.txt` marker matching unpackerr's convention so
# the daily rar-backlog scanner doesn't re-flag it.
#
# Depth-agnostic by design: rtorrent gives us the exact path the files
# landed under, so paths like /data/TV/<Show>/Season 1/<release>/foo.rar
# work the same as /data/Movies/<release>/foo.rar — no watch-path
# enumeration to maintain.
#
# Idempotent: re-invocation on an already-processed directory is a
# no-op (marker present). On extraction failure we leave no marker,
# so flood/scripts/rar-backlog.sh catches the stuck folder on its
# next daily run and Gatus alerts.
#
# Why bsdtar (libarchive) — see flood/Dockerfile for the full rationale
# (short version: alpine dropped unrar, alpine's p7zip resolves to a
# slim 7zip without the RAR codec, libarchive ships permissive RAR
# read + multi-volume support).
#
# Why we don't trust bsdtar's exit code: libarchive emits "Truncated
# RAR file data" at the last-volume boundary on legacy multi-volume
# RAR sets (.rar + .r00, .r01, …) even after extracting the contents
# successfully. We verify by comparing the count of non-archive
# "keeper" files in the target dir before vs after — same heuristic
# the rtorrent-cleanup.sh ABORT guard uses, run in reverse.
#
# Safety layers (mirroring rtorrent-cleanup.sh):
#   1. Path guard — only operate under /data/{Movies,TV,Kids}.
#   2. Marker check — never re-extract an already-processed dir.
#   3. Post-extract verification — only drop the marker if extraction
#      actually produced new content.

set -u

LOG_FILE=/flood-db/rtorrent-extract.log
exec >> "$LOG_FILE" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') invoked argc=$# argv=[$*] ==="

BASE="${1:-}"

log() { echo "[rtorrent-extract] $*"; }

# Count files that are NOT RAR pieces, NOT scene metadata, and NOT
# sample artifacts. Same set the rtorrent-cleanup.sh keeper check uses,
# plus the _unpackerred.* marker so re-runs don't see "themselves" as
# new keepers.
count_keepers() {
    find "$1" -maxdepth 1 -type f \
        ! -iname '*.rar' \
        ! -iname '*.r[0-9][0-9]' \
        ! -iname '*.part[0-9]*.rar' \
        ! -iname '*.sfv' \
        ! -iname '*.srr' \
        ! -iname '*.srs' \
        ! -iname '*.nfo' \
        ! -iname '*sample*' \
        ! -iname '_unpackerred.*' \
        2>/dev/null | wc -l | tr -d ' '
}

# --- Path guard ------------------------------------------------------
case "$BASE" in
    /data/Movies/*|/data/TV/*|/data/Kids/*) ;;
    *)
        log "skip: base_path outside watched roots: $BASE"
        exit 0
        ;;
esac

if [ ! -d "$BASE" ]; then
    # Single-file torrent (base_path is the file itself). The only
    # interesting case would be a bare .rar download — vanishingly rare
    # in practice, so not handled here.
    log "skip: base_path is not a directory (single-file torrent?): $BASE"
    exit 0
fi

# --- Locate the entry-point archive ---------------------------------
# Recursive walk at any depth. Precedence (mirrors golift/xtractr's
# getCompressedFiles):
#   1. *.rar that is NOT *.part*.rar — modern single-volume, OR legacy
#      multi-volume where the first volume is .rar and continuations
#      are .r00, .r01, …
#   2. *.part01.rar / *.part001.rar — RAR5 multi-volume.
#   3. *.r00 only if no .rar coexists in the same directory.
#
# `head -n 1` is fine — bsdtar handles multi-volume given any first
# volume in the same directory.

archive=$(find "$BASE" -type f -iname '*.rar' ! -iname '*.part*.rar' 2>/dev/null | head -n 1)

if [ -z "$archive" ]; then
    archive=$(find "$BASE" -type f \( -iname '*.part01.rar' -o -iname '*.part001.rar' \) 2>/dev/null | head -n 1)
fi

if [ -z "$archive" ]; then
    candidate=$(find "$BASE" -type f -iname '*.r00' 2>/dev/null | head -n 1)
    if [ -n "$candidate" ]; then
        cdir=$(dirname "$candidate")
        # Only accept .r00 as entry when no .rar coexists in the same
        # directory (some legacy releases name the first volume .rar
        # and we don't want to start mid-stream).
        if [ -z "$(find "$cdir" -maxdepth 1 -type f -iname '*.rar' 2>/dev/null | head -n 1)" ]; then
            archive="$candidate"
        fi
    fi
fi

if [ -z "$archive" ]; then
    log "no archive found in $BASE — non-rar torrent, nothing to do"
    exit 0
fi

# --- Marker check ---------------------------------------------------
dir=$(dirname "$archive")
marker_name="_unpackerred.$(basename "$dir").txt"
marker="$dir/$marker_name"

if [ -e "$marker" ]; then
    log "skip: $marker_name already present in $dir"
    exit 0
fi

# --- Extract --------------------------------------------------------
pre=$(count_keepers "$dir")
log "extracting $archive into $dir (pre-extract keepers: $pre)"

# bsdtar -x extracts; -f names the archive file; -C sets target dir.
# stdout/stderr already redirected to $LOG_FILE via exec above. We
# intentionally don't check $? — libarchive's "Truncated RAR file
# data" exit code can fire on a full successful extraction. Verify
# below by comparing keeper counts.
( cd "$dir" && bsdtar -xf "$archive" ) || true

post=$(count_keepers "$dir")

if [ "$post" -gt "$pre" ]; then
    printf 'Extracted %s on %s by rtorrent-extract.sh (keepers %d → %d)\n' \
        "$(basename "$archive")" "$(date -Iseconds)" "$pre" "$post" > "$marker"
    log "done: $dir ($pre → $post keepers)"
    exit 0
else
    log "ERROR: bsdtar produced no new keepers in $dir — leaving stuck for rar-backlog to alert"
    exit 1
fi
