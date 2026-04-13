#!/usr/bin/env bash
#
# Plex write-pileup stress test.
#
# Simulates concurrent playback sessions + metadata browsing for N seconds,
# then reports on lock storms, slow queries, and canary latency.
#
# Usage: ./plex-writeload-test.sh [duration_seconds]
#
set -euo pipefail

TOKEN="${PLEX_TOKEN:-jjfoyxSMazy7_z28gf4h}"
URL="${PLEX_URL:-http://localhost:32400}"
DURATION="${1:-300}"  # default 5 minutes
NUM_SESSIONS=3

# Pick a few ratingKeys from the library to simulate playback against
# We need actual items that exist in the library
echo "=== Discovering test items ==="
TEST_ITEMS=$(curl -sf --max-time 30 "$URL/library/sections/2/all?type=2&X-Plex-Token=$TOKEN" 2>&1 | python3 -c "
import sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
keys = [d.get('ratingKey') for d in root.findall('.//Directory')[:20]]
print(' '.join(keys))
" 2>&1)
echo "Test items: $TEST_ITEMS"

# Also get some episode ratingKeys for timeline simulation
FIRST_SHOW=$(echo "$TEST_ITEMS" | awk '{print $1}')
EPISODES=$(curl -sf --max-time 30 "$URL/library/metadata/$FIRST_SHOW/allLeaves?X-Plex-Token=$TOKEN" 2>&1 | python3 -c "
import sys, xml.etree.ElementTree as ET
root = ET.fromstring(sys.stdin.read())
keys = [v.get('ratingKey') for v in root.findall('.//Video')[:$NUM_SESSIONS]]
print(' '.join(keys))
" 2>&1)
echo "Episode items: $EPISODES"

# Log baseline counts (always emit a single integer, never fail)
count_lines() {
    local pat=$1
    local n
    n=$(docker exec plex grep -c "$pat" '/config/Library/Application Support/Plex Media Server/Logs/Plex Media Server.log' 2>/dev/null) || n=0
    # grep returns 1 if no matches, which makes n empty
    [ -z "$n" ] && n=0
    printf '%s' "$n"
}
BASELINE_STORMS=$(count_lines 'threads are waiting')
BASELINE_SLOW=$(count_lines 'SLOW QUERY')
echo ""
echo "=== Baseline ==="
echo "Lock storms: $BASELINE_STORMS"
echo "Slow queries: $BASELINE_SLOW"
echo ""

# Simulated playback session
playback_session() {
    local ep_key=$1
    local session_id="test-$$-$ep_key"
    local duration_ms=3600000  # 1 hour fake runtime
    local progress=0
    local end_time=$(($(date +%s) + DURATION))

    while [ $(date +%s) -lt $end_time ]; do
        progress=$((progress + 10000))  # 10 seconds
        # Send timeline update
        curl -sf --max-time 10 -o /dev/null \
            "$URL/:/timeline?ratingKey=$ep_key&key=/library/metadata/$ep_key&state=playing&time=$progress&duration=$duration_ms&playbackTime=$progress&X-Plex-Token=$TOKEN" 2>/dev/null || true
        # Also update view state
        curl -sf --max-time 10 -o /dev/null \
            "$URL/:/progress?key=/library/metadata/$ep_key&identifier=com.plexapp.plugins.library&time=$progress&state=playing&X-Plex-Token=$TOKEN" 2>/dev/null || true
        sleep 3
    done
}

# Metadata browsing simulation
browse_session() {
    local items="$1"
    local end_time=$(($(date +%s) + DURATION))

    while [ $(date +%s) -lt $end_time ]; do
        for key in $items; do
            curl -sf --max-time 5 -o /dev/null \
                "$URL/library/metadata/$key?includeUserState=1&X-Plex-Token=$TOKEN" 2>/dev/null || true
        done
        sleep 2
    done
}

# Canary latency monitoring
canary_latency() {
    local log_file=$1
    local end_time=$(($(date +%s) + DURATION))
    while [ $(date +%s) -lt $end_time ]; do
        local t_start=$(date +%s%N)
        local rc=$(curl -sf --max-time 30 -o /dev/null -w "%{http_code}" "$URL/library/sections?X-Plex-Token=$TOKEN" 2>/dev/null || echo "000")
        local t_end=$(date +%s%N)
        local elapsed_ms=$(( (t_end - t_start) / 1000000 ))
        echo "$(date '+%H:%M:%S') $rc ${elapsed_ms}ms" >> "$log_file"
        sleep 10
    done
}

CANARY_LOG=$(mktemp)
echo "Canary log: $CANARY_LOG"

echo "=== Starting test (${DURATION}s) ==="
echo "  $NUM_SESSIONS playback sessions + metadata browsing + canary"
echo "  Start: $(date '+%H:%M:%S')"

# Launch sessions in background
PIDS=()
for ep in $EPISODES; do
    playback_session "$ep" &
    PIDS+=($!)
done

browse_session "$TEST_ITEMS" &
PIDS+=($!)

canary_latency "$CANARY_LOG" &
PIDS+=($!)

# Wait for all
for pid in "${PIDS[@]}"; do
    wait $pid 2>/dev/null || true
done

echo "  End: $(date '+%H:%M:%S')"

# Analyze results
FINAL_STORMS=$(count_lines 'threads are waiting')
FINAL_SLOW=$(count_lines 'SLOW QUERY')
DELTA_STORMS=$((FINAL_STORMS - BASELINE_STORMS))
DELTA_SLOW=$((FINAL_SLOW - BASELINE_SLOW))

echo ""
echo "=== Results ==="
echo "Lock storms triggered: $DELTA_STORMS (baseline $BASELINE_STORMS → $FINAL_STORMS)"
echo "Slow queries triggered: $DELTA_SLOW (baseline $BASELINE_SLOW → $FINAL_SLOW)"

echo ""
echo "=== Canary latency (library sections GET) ==="
if [ -f "$CANARY_LOG" ] && [ -s "$CANARY_LOG" ]; then
    cat "$CANARY_LOG"
    echo ""
    echo "Summary:"
    awk '{
        if ($2 == "200") {
            gsub("ms", "", $3);
            n = $3 + 0;
            total += n;
            if (count == 0 || n > max) max = n;
            if (count == 0 || n < min) min = n;
            count++;
        } else {
            errors++;
        }
    }
    END {
        if (count > 0) {
            printf "  Samples: %d OK, %d errors\n", count, errors+0;
            printf "  Min: %dms, Avg: %.0fms, Max: %dms\n", min, total/count, max;
        } else {
            printf "  No successful samples\n";
        }
    }' "$CANARY_LOG"
fi

rm -f "$CANARY_LOG"
