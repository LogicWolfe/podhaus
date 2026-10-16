#!/bin/sh
# Monthly cleanup + VACUUM of Plex's statistics_bandwidth table.
#
# Plex tracks every playback bandwidth event in this table and provides no
# UI/API/scheduled task to prune it. Left alone, it grows unbounded —
# bilby's library DB hit 47 GB / 796 million rows over 9 years before we
# noticed (the April 2026 outage). After the offline rebuild it was
# 3,405 rows and 217 MB; this script keeps it that way.
#
# Online DELETE is safe under WAL journaling (which Plex's library.db
# uses): the DELETE acquires a brief write lock, concurrent readers are
# unaffected, and other writers stall for milliseconds at most.
#
# VACUUM is the disk-reclaim step. Without it, DELETE just marks pages
# free and the file size plateaus rather than shrinks. With it, the file
# rewrites compactly and reclaims space. VACUUM acquires an EXCLUSIVE
# lock on the database — every other reader and writer is blocked until
# it completes. For a clean ~250 MB DB this is sub-second to a few
# seconds at NVMe speeds. The 4 AM schedule sits well outside any
# typical viewing window. If VACUUM ever times out the autoheal threshold
# (15s timeout × 3 retries × 60s interval ≈ 3.5 min), Plex will get
# restarted mid-VACUUM — the rebuild aborts cleanly because SQLite uses
# a temp-file pattern, but you'll get a brief Plex outage.
#
# Logs to stdout — Alloy ships container logs, so the cleanup audit
# trail lands in the logging stack automatically.

set -eu

DB_PATH="/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
PLEX_SQLITE="/usr/lib/plexmediaserver/Plex SQLite"
RETENTION_DAYS=30

export LD_LIBRARY_PATH=/usr/lib/plexmediaserver/lib

run_sql() {
    "$PLEX_SQLITE" "$DB_PATH" "$1"
}

ts() {
    date '+%Y-%m-%dT%H:%M:%S%z'
}

before_rows=$(run_sql "SELECT COUNT(*) FROM statistics_bandwidth;")
before_oldest=$(run_sql "SELECT COALESCE(datetime(MIN(at),'unixepoch','localtime'), 'empty') FROM statistics_bandwidth;")
before_size=$(stat -c %s "$DB_PATH")

run_sql "DELETE FROM statistics_bandwidth WHERE at < strftime('%s','now','-${RETENTION_DAYS} days');"

after_rows=$(run_sql "SELECT COUNT(*) FROM statistics_bandwidth;")
after_oldest=$(run_sql "SELECT COALESCE(datetime(MIN(at),'unixepoch','localtime'), 'empty') FROM statistics_bandwidth;")
deleted=$((before_rows - after_rows))

printf '[stats-cleanup %s] DELETE retention=%dd  rows: %d -> %d (-%d)  oldest: %s -> %s\n' \
    "$(ts)" \
    "$RETENTION_DAYS" \
    "$before_rows" "$after_rows" "$deleted" \
    "$before_oldest" "$after_oldest"

vacuum_start=$(date +%s)
run_sql "VACUUM;"
vacuum_end=$(date +%s)
after_size=$(stat -c %s "$DB_PATH")
reclaimed=$((before_size - after_size))

printf '[stats-cleanup %s] VACUUM took=%ds  size: %d -> %d bytes (reclaimed %d)\n' \
    "$(ts)" \
    "$((vacuum_end - vacuum_start))" \
    "$before_size" "$after_size" "$reclaimed"
