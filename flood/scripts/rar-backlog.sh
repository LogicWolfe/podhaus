#!/bin/sh
# Daily safety-net check for the rtorrent RAR-extraction pipeline.
#
# Primary extraction happens in real time via the rtorrent-extract.sh
# event.download.finished hook (in flood/conf/rtorrent.rc). This script
# is the cron-driven backstop for the whole download pipeline, two checks:
#   1. Extraction: scans /data/torrents for folders containing RAR pieces
#      >= AGE_THRESHOLD old with no non-RAR/non-detritus content alongside
#      them — RARs present but nothing extracted.
#   2. Publish: completed torrents whose media never hardlinked into the
#      Plex library (flood-publish.py --gaps). This is the safety net for
#      the no-delete-time-guard model — a publish gap surfaces here before
#      the user would ever "Remove and delete data". See
#      docs/runbooks/flood.html.
#
# Pushes result to Gatus heartbeat endpoint:
#   0 unhealthy → success=true
#   ≥1 unhealthy → success=false + body listing first few paths
# If the script itself never runs (container dead, ofelia broken), Gatus
# misses the 25h heartbeat and alerts as a dead-man's switch.
#
# Scheduled via an Ofelia label on each Flood container; runs at 04:50 in the
# scheduler's local timezone.

set -u

AGE_MINUTES=120  # 2 hours — RARs younger than this may still be extracting
TOKEN="${GATUS_OFELIA_PUSH_TOKEN:-}"

if [ -z "$TOKEN" ]; then
    echo "[rar-backlog] ERROR: GATUS_OFELIA_PUSH_TOKEN not set in env" >&2
    exit 1
fi
: "${GATUS_BASE_URL:?GATUS_BASE_URL is required}"
: "${GATUS_RAR_ENDPOINT_ID:?GATUS_RAR_ENDPOINT_ID is required}"
GATUS_URL="${GATUS_BASE_URL%/}/api/v1/endpoints/${GATUS_RAR_ENDPOINT_ID}/external"

unhealthy_list=/tmp/rar-backlog-unhealthy.$$
dir_list=/tmp/rar-backlog-dirs.$$
: > "$unhealthy_list"

# Find folders containing RAR pieces older than the age threshold.
# Folder names may contain spaces (common for TV show names); newlines
# in paths are assumed to not occur (would break newline-separated list).
# busybox find's -printf doesn't support \0 reliably, so we newline-
# separate and quote carefully via `while IFS= read -r`.
find /data/torrents \
    -type f -mmin +$AGE_MINUTES \
    \( -iname '*.rar' -o -iname '*.r[0-9][0-9]' -o -iname '*.part[0-9]*.rar' \) \
    2>/dev/null \
    | while IFS= read -r rarfile; do
        dirname -- "$rarfile"
    done \
    | sort -u > "$dir_list"

while IFS= read -r dir; do
    # A keeper beside the archive proves extraction produced usable output.
    keep_count=$(find "$dir" -maxdepth 1 -type f \
        ! -iname '*.rar' \
        ! -iname '*.r[0-9][0-9]' \
        ! -iname '*.part[0-9]*.rar' \
        ! -iname '*.sfv' \
        ! -iname '*.srr' \
        ! -iname '*.srs' \
        ! -iname '*.nfo' \
        ! -iname '*sample*' \
        2>/dev/null | wc -l)

    if [ "$keep_count" -eq 0 ]; then
        printf '%s\n' "$dir" >> "$unhealthy_list"
    fi
done < "$dir_list"
rm -f "$dir_list"

# --- Publish-gap check ----------------------------------------------
# Completed torrents whose media never hardlinked into the library.
# flood-publish.py --gaps reports them from rtorrent's own completion
# state (one torrent name per line); fold into the same heartbeat.
if gaps=$(python3 /scripts/flood-publish.py --gaps 2>>/flood-db/flood-publish.log); then
    printf '%s\n' "$gaps" | while IFS= read -r name; do
        [ -n "$name" ] && printf 'unpublished: %s\n' "$name" >> "$unhealthy_list"
    done
else
    printf 'unpublished: gap-check-failed (rtorrent unreachable?)\n' >> "$unhealthy_list"
fi

unhealthy_count=$(wc -l < "$unhealthy_list" | tr -d ' ')

if [ "$unhealthy_count" -eq 0 ]; then
    echo "[rar-backlog] healthy: no unextracted RAR folders or publish gaps"
    wget -qO- --post-data='' \
        --header="Authorization: Bearer ${TOKEN}" \
        "${GATUS_URL}?success=true" > /dev/null
    rm -f "$unhealthy_list"
    exit 0
fi

echo "[rar-backlog] UNHEALTHY: ${unhealthy_count} extraction/publish issues"
sed 's/^/  /' "$unhealthy_list"

# Build a short URL-safe error string: count + first 3 item basenames.
# Gatus renders this in [RESULT_ERRORS] in the alert email. Full list
# remains in the stdout above (→ Alloy → ClickStack).
sample=$(head -3 "$unhealthy_list" | awk -F/ '{print $NF}' | tr '\n' ',' | sed 's/,$//')
error_msg="${unhealthy_count} extraction/publish issues; sample: ${sample}"
# Percent-encode spaces → +, plus the delimiters that break query parsing
# (%, &, #, ?, ", ;, ,). Busybox has no `jq -r @uri`, so do it crudely.
error_enc=$(printf '%s' "$error_msg" \
    | sed 's/%/%25/g; s/ /+/g; s/&/%26/g; s/#/%23/g; s/?/%3F/g; s/"/%22/g; s/;/%3B/g; s/,/%2C/g')

wget -qO- --post-data="" \
    --header="Authorization: Bearer ${TOKEN}" \
    "${GATUS_URL}?success=false&error=${error_enc}" > /dev/null
rm -f "$unhealthy_list"
exit 0
