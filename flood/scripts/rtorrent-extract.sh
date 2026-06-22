#!/bin/sh
# Called by rtorrent's event.download.finished hook with $d.base_path= as $1.
#
# Real-time in-place RAR extraction for completed torrents. Torrents now
# download under /data/torrents (see docs/plans/flood-atomic-publish.md);
# rtorrent passes the exact base_path the torrent landed under, so we walk
# that subtree, extract every RAR set found via bsdtar in place, and drop a
# `_unpackerred.<dir>.txt` marker per extracted dir. flood-publish.py then
# hardlinks the extracted media into the Plex library.
#
# Every RAR set under base_path, not just the first: a season-pack torrent
# can carry one release subfolder per episode, each with its own RAR set.
# (The previous `find … | head -n 1` extracted only the first and silently
# skipped the rest, with the marker fooling rar-backlog into thinking the
# folder was handled.)
#
# Idempotent: a dir with its marker already present is skipped. On
# extraction failure we leave no marker, so flood/scripts/rar-backlog.sh
# catches the stuck folder on its next daily run and Gatus alerts.
#
# Why bsdtar (libarchive) — see flood/Dockerfile. Why we don't trust its
# exit code: libarchive emits "Truncated RAR file data" at the last-volume
# boundary on legacy multi-volume sets even after a full extraction, so we
# verify by comparing the count of non-archive "keeper" files before vs
# after.

set -u

LOG_FILE=/flood-db/rtorrent-extract.log
exec >> "$LOG_FILE" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') invoked argc=$# argv=[$*] ==="

BASE="${1:-}"

log() { echo "[rtorrent-extract] $*"; }

# Count files that are NOT RAR pieces, NOT scene metadata, and NOT sample
# artifacts (plus the marker itself, so re-runs don't see it as a keeper).
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
# Downloads live under /data/torrents now (rtorrent-redirected at insert).
case "$BASE" in
    /data/torrents/*) ;;
    *)
        log "skip: base_path outside /data/torrents: $BASE"
        exit 0
        ;;
esac

if [ ! -d "$BASE" ]; then
    # Single-file torrent (base_path is the file itself). A bare .rar
    # download is vanishingly rare; not handled here.
    log "skip: base_path is not a directory (single-file torrent?): $BASE"
    exit 0
fi

# --- Pick the entry-point archive in one directory -------------------
# Precedence (mirrors golift/xtractr's getCompressedFiles), scoped to a
# single dir so each release subfolder is handled independently:
#   1. *.rar that is NOT *.part*.rar — modern single-volume, or legacy
#      multi-volume first volume (.rar + .r00, .r01, …)
#   2. *.part01.rar / *.part001.rar — RAR5 multi-volume.
#   3. *.r00 only if no .rar coexists in the same directory.
entry_archive() {
    d="$1"
    a=$(find "$d" -maxdepth 1 -type f -iname '*.rar' ! -iname '*.part*.rar' 2>/dev/null | head -n 1)
    [ -z "$a" ] && a=$(find "$d" -maxdepth 1 -type f \( -iname '*.part01.rar' -o -iname '*.part001.rar' \) 2>/dev/null | head -n 1)
    if [ -z "$a" ]; then
        c=$(find "$d" -maxdepth 1 -type f -iname '*.r00' 2>/dev/null | head -n 1)
        if [ -n "$c" ] && [ -z "$(find "$d" -maxdepth 1 -type f -iname '*.rar' 2>/dev/null | head -n 1)" ]; then
            a="$c"
        fi
    fi
    printf '%s' "$a"
}

# --- Extract one directory's RAR set --------------------------------
extract_dir() {
    e_dir="$1"
    e_archive=$(entry_archive "$e_dir")
    [ -z "$e_archive" ] && { log "no entry-point archive in $e_dir"; return 0; }

    e_marker="$e_dir/_unpackerred.$(basename "$e_dir").txt"
    if [ -e "$e_marker" ]; then
        log "skip: marker already present in $e_dir"
        return 0
    fi

    pre=$(count_keepers "$e_dir")
    log "extracting $e_archive into $e_dir (pre-extract keepers: $pre)"
    ( cd "$e_dir" && bsdtar -xf "$e_archive" ) || true
    post=$(count_keepers "$e_dir")

    if [ "$post" -gt "$pre" ]; then
        printf 'Extracted %s on %s by rtorrent-extract.sh (keepers %d → %d)\n' \
            "$(basename "$e_archive")" "$(date -Iseconds)" "$pre" "$post" > "$e_marker"
        log "done: $e_dir ($pre → $post keepers)"
        return 0
    fi
    log "ERROR: bsdtar produced no new keepers in $e_dir — leaving stuck for rar-backlog to alert"
    return 1
}

# --- Walk every directory under BASE that holds a RAR set -----------
dir_list=$(mktemp)
find "$BASE" -type f \
    \( -iname '*.rar' -o -iname '*.r[0-9][0-9]' -o -iname '*.part[0-9]*.rar' \) \
    -exec dirname {} \; 2>/dev/null | sort -u > "$dir_list"

if [ ! -s "$dir_list" ]; then
    log "no archive found under $BASE — non-rar torrent, nothing to do"
    rm -f "$dir_list"
    exit 0
fi

rc=0
while IFS= read -r d; do
    extract_dir "$d" || rc=1
done < "$dir_list"
rm -f "$dir_list"

exit "$rc"
