#!/bin/sh
# Reconcile Pouch's .stignore allowlist with the set of rtorrent torrents
# tagged "pinelake" that have finished downloading.
#
# Triggered two ways:
#   1. rtorrent event.download.finished hook (zero-latency)
#   2. ofelia tick every 5min (catches tag-applied-after-completion)
#
# Both call this script with no args. Single code path = full scan of
# /flood-db/*.torrent.rtorrent (rtorrent's own session state). The on-disk
# state is authoritative; Flood persists tags into rtorrent's d.custom1.
#
# Insert-only by design. Untagging or deleting a torrent doesn't remove
# its line from .stignore — the user manages removals by hand.
#
# Safety layers:
#   - flock on a sidecar lock; periodic + event triggers can't race.
#   - .stignore writes use tempfile + atomic rename; group inherited via
#     setgid on /mnt/pouch.
#   - Skips entries whose base_path doesn't sit under /data/.

set -u

LOG_FILE=/flood-db/pinelake-stignore.log
STIGNORE=/data/.stignore
LOCK=/flood-db/pinelake-stignore.lock
SESSION_DIR=/flood-db

exec >> "$LOG_FILE" 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*"; }

# Dead-man's-switch heartbeat — push on any clean exit so a missing push
# means ofelia stopped ticking this job (see gatus
# heartbeat_pinelake-stignore). Pushing on the flock-contention exit too
# is fine: it still proves ofelia ran us.
heartbeat() {
    [ -n "${GATUS_OFELIA_PUSH_TOKEN:-}" ] || return 0
    wget -qO- --timeout=10 --post-data='' \
        --header="Authorization: Bearer ${GATUS_OFELIA_PUSH_TOKEN}" \
        "http://gatus:8080/api/v1/endpoints/heartbeat_pinelake-stignore/external?success=true" \
        >/dev/null 2>&1 || log "WARN: gatus heartbeat push failed"
}
trap 'rc=$?; [ "$rc" -eq 0 ] && heartbeat' EXIT

# Single-flight. If the event hook and the cron tick collide, second
# caller exits cleanly — the first run sees the same session-file state
# either way.
exec 9>"$LOCK"
if ! flock -n 9; then
    exit 0
fi

if [ ! -f "$STIGNORE" ]; then
    log "no .stignore at $STIGNORE — skipping"
    exit 0
fi

# --- Scan session files ---------------------------------------------
# Bencode walker: alphabetically-ordered top-level dict with the keys we
# care about (complete, custom1, directory). Walks the structure properly
# rather than substring-matching, so a path containing "9:directory" can't
# false-match.
candidates=$(awk '
    BEGIN { OFS = "\t" }
    {
        s = $0
        n = length(s)
        complete = 0
        custom1 = ""
        directory = ""
        pos = 2          # skip leading "d"
        while (pos <= n) {
            c = substr(s, pos, 1)
            if (c == "e") break

            # Read key (always a length-prefixed string).
            colon = index(substr(s, pos), ":")
            if (colon == 0) break
            klen = substr(s, pos, colon - 1) + 0
            key  = substr(s, pos + colon, klen)
            pos += colon + klen

            # Dispatch by value type marker.
            c = substr(s, pos, 1)
            if (c == "i") {
                e = index(substr(s, pos), "e")
                if (key == "complete") complete = substr(s, pos + 1, e - 2) + 0
                pos += e
            } else if (c >= "0" && c <= "9") {
                colon = index(substr(s, pos), ":")
                slen  = substr(s, pos, colon - 1) + 0
                val   = substr(s, pos + colon, slen)
                if (key == "custom1") custom1 = val
                else if (key == "directory") directory = val
                pos += colon + slen
            } else if (c == "d" || c == "l") {
                # Skip nested dict/list with depth tracking.
                depth = 1; pos++
                while (depth > 0 && pos <= n) {
                    cc = substr(s, pos, 1)
                    if (cc == "d" || cc == "l") { depth++; pos++ }
                    else if (cc == "e") { depth--; pos++ }
                    else if (cc == "i") {
                        e = index(substr(s, pos), "e")
                        pos += e
                    } else if (cc >= "0" && cc <= "9") {
                        colon = index(substr(s, pos), ":")
                        slen  = substr(s, pos, colon - 1) + 0
                        pos += colon + slen
                    } else break
                }
            } else break
        }

        if (complete != 1) next
        if (directory == "") next

        # custom1 is URL-encoded comma-separated; "pinelake" survives the
        # encoding as itself, so exact CSV-element match is safe.
        m = split(custom1, tags, ",")
        for (i = 1; i <= m; i++) {
            if (tags[i] == "pinelake") {
                print directory
                next
            }
        }
    }
' "$SESSION_DIR"/*.torrent.rtorrent 2>/dev/null)

if [ -z "$candidates" ]; then
    exit 0
fi

# --- Build pending insert set ---------------------------------------
new_lines=/tmp/pinelake-stignore.new.$$
pending=/tmp/pinelake-stignore.pending.$$
: > "$new_lines"
: > "$pending"
trap 'rm -f "$new_lines" "$pending"' EXIT

echo "$candidates" | while IFS= read -r dir; do
    case "$dir" in
        /data/*) printf '!%s\n' "${dir#/data/}" >> "$new_lines" ;;
    esac
done

while IFS= read -r line; do
    grep -Fxq -- "$line" "$STIGNORE" || printf '%s\n' "$line" >> "$pending"
done < "$new_lines"

if [ ! -s "$pending" ]; then
    exit 0
fi

log "adding $(wc -l < "$pending" | tr -d ' ') line(s) to $STIGNORE"

# --- Insert each pending line alphabetically into matching block ----
# Tempfile in /data so the rename stays on the same filesystem (atomic
# on NFS). setgid on /mnt/pouch ensures the new file inherits the
# existing group.
tmp=$(mktemp -p /data ".stignore.XXXXXX") || {
    log "ERROR: mktemp failed in /data"
    exit 1
}
cp "$STIGNORE" "$tmp"

while IFS= read -r new_line; do
    log "  + $new_line"
    awk -v new_line="$new_line" '
        BEGIN {
            inserted = 0
            in_block = 0
            # Top-level prefix !<TopLevel>/ identifies the matching block.
            if (match(new_line, /^![^\/]+\//)) {
                prefix = substr(new_line, RSTART, RLENGTH)
            } else {
                prefix = ""
            }
        }
        {
            line = $0
            is_block_line = (prefix != "" && index(line, prefix) == 1)

            if (!inserted) {
                if (in_block && !is_block_line) {
                    # Block just ended — new_line is alphabetically last.
                    print new_line
                    inserted = 1
                    in_block = 0
                } else if (is_block_line) {
                    in_block = 1
                    # Case-insensitive compare — the existing blocks sort
                    # "Little Big Man" → "logan" → "Mad Max", not ASCII.
                    if (tolower(new_line) < tolower(line)) {
                        print new_line
                        inserted = 1
                    }
                } else if (!in_block && line == "**") {
                    # No matching block exists; slot in just before "**".
                    print new_line
                    inserted = 1
                }
            }
            print line
        }
        END {
            if (!inserted) print new_line
        }
    ' "$tmp" > "$tmp.next"
    mv "$tmp.next" "$tmp"
done < "$pending"

mv "$tmp" "$STIGNORE"
log "done"
exit 0
