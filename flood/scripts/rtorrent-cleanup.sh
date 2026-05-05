#!/bin/sh
# Called by rtorrent's event.download.erased hook with $d.base_path= as $1.
# Deletes RAR pieces + scene detritus from a removed torrent's folder,
# preserving the extracted content + subtitles.
#
# Safety layers (defense-in-depth):
#   1. Path guard       — only operates under /data/{Movies,TV,Kids}
#   2. RAR detection    — non-RAR torrents are a no-op
#   3. Extraction guard — refuses to delete if no non-RAR/non-detritus
#                         content exists in the folder, because that
#                         implies extraction never happened (unpackerr
#                         died, permission error, etc.) and deleting
#                         the RARs would be destructive.
#
# Exits 0 on every path to keep the rtorrent hook clean.

set -u

# Self-logging to a persistent file so invocations are observable even
# when called via rtorrent's `execute2.nothrow` (which discards stdout).
# Without this, a silently-broken hook is indistinguishable from one
# that ran cleanly. Append-only — rotate manually if it grows.
LOG_FILE=/flood-db/rtorrent-cleanup.log
exec >> "$LOG_FILE" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') invoked argc=$# argv=[$*] ==="

BASE="${1:-}"

log() { echo "[rtorrent-cleanup] $*"; }

# --- Path guard ------------------------------------------------------
case "$BASE" in
    /data/Movies/*|/data/TV/*|/data/Kids/*) ;;
    *)
        log "skip: base_path outside watched roots: $BASE"
        exit 0
        ;;
esac

if [ ! -d "$BASE" ]; then
    log "skip: base_path does not exist or not a directory: $BASE"
    exit 0
fi

# --- RAR detection ---------------------------------------------------
RAR_COUNT=$(find "$BASE" -type f \
    \( -iname '*.rar' -o -iname '*.r[0-9][0-9]' -o -iname '*.part[0-9]*.rar' \) \
    | wc -l)

if [ "$RAR_COUNT" -eq 0 ]; then
    log "skip: non-RAR torrent: $BASE"
    exit 0
fi

# --- Extraction guard ------------------------------------------------
# Count files that are NOT RAR pieces, NOT scene metadata, and NOT
# sample artifacts. If the result is zero, unpackerr hasn't extracted
# anything — bail out rather than delete the only copy of the content.
KEEP_COUNT=$(find "$BASE" -type f \
    ! -iname '*.rar' \
    ! -iname '*.r[0-9][0-9]' \
    ! -iname '*.part[0-9]*.rar' \
    ! -iname '*.sfv' \
    ! -iname '*.srr' \
    ! -iname '*.srs' \
    ! -iname '*.nfo' \
    ! -iname '*sample*' \
    ! -ipath '*/Sample/*' \
    ! -ipath '*/Proof/*' \
    | wc -l)

if [ "$KEEP_COUNT" -eq 0 ]; then
    log "ABORT: RAR torrent has no extracted content in $BASE (unpackerr may have failed) — leaving files in place"
    exit 0
fi

log "cleaning RAR torrent: $BASE ($RAR_COUNT rar files, $KEEP_COUNT keepers)"

# --- Delete RAR + metadata ------------------------------------------
find "$BASE" -type f \
    \( -iname '*.rar' \
    -o -iname '*.r[0-9][0-9]' \
    -o -iname '*.part[0-9]*.rar' \
    -o -iname '*.sfv' \
    -o -iname '*.srr' \
    -o -iname '*.srs' \
    -o -iname '*.nfo' \
    \) -print -delete

# --- Delete sample + proof directories ------------------------------
find "$BASE" -type d \( -iname sample -o -iname proof \) -print -exec rm -rf {} + 2>/dev/null

# --- Delete top-level sample video files ----------------------------
find "$BASE" -maxdepth 2 -type f -iname '*sample*' \
    \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.avi' -o -iname '*.m4v' -o -iname '*.ts' \) \
    -print -delete

# --- Remove now-empty subdirs (never $BASE itself) ------------------
find "$BASE" -mindepth 1 -type d -empty -print -delete

log "done: $BASE"
exit 0
