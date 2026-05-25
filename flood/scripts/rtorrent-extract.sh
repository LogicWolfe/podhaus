#!/bin/sh
# Called by rtorrent's event.download.finished hook with $d.base_path= as $1.
#
# Real-time in-place RAR extraction for completed torrents. Replaces the
# previous unpackerr stack: rtorrent already knows the exact base_path
# each torrent landed under, so we walk that subtree at any depth for
# the archive entry-point, run 7za against it in place, and drop a
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
# Safety layers (mirroring rtorrent-cleanup.sh):
#   1. Path guard — only operate under /data/{Movies,TV,Kids}.
#   2. Marker check — never re-extract an already-processed dir.
#   3. Fail-loud — extraction failure leaves the rar set in place
#      with NO marker, so the daily safety-net surfaces it.

set -u

LOG_FILE=/flood-db/rtorrent-extract.log
exec >> "$LOG_FILE" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') invoked argc=$# argv=[$*] ==="

BASE="${1:-}"

log() { echo "[rtorrent-extract] $*"; }

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
# Recursive walk at any depth. Precedence mirrors golift/xtractr's
# getCompressedFiles:
#   1. *.rar that is NOT *.part*.rar — modern single-volume, OR legacy
#      multi-volume where the first volume is .rar and continuations
#      are .r00, .r01, …
#   2. *.part01.rar / *.part001.rar — RAR5 multi-volume.
#   3. *.r00 only if no .rar coexists in the same directory.
#
# `head -n 1` is fine — 7za handles multi-volume given any first part.

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
log "extracting $archive into $dir"

# `7za x` extracts; -y answers yes to overwrite prompts; -o<dir> sets
# output path (no space between -o and the path — 7za convention).
# Output is appended to $LOG_FILE via the exec redirect above.
if 7za x -y -o"$dir" "$archive"; then
    printf 'Extracted %s on %s by rtorrent-extract.sh\n' \
        "$(basename "$archive")" "$(date -Iseconds)" > "$marker"
    log "done: $dir"
    exit 0
else
    log "ERROR: 7za extraction failed for $archive — leaving stuck for rar-backlog to alert"
    exit 1
fi
