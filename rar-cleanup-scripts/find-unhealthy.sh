#!/bin/sh
# Prints folder paths under /data/{Movies,TV,Kids} that contain RAR pieces
# older than 2h with no sibling extracted content (same detection as the
# live flood/rar-backlog.sh, duplicated here so cleanup tooling doesn't
# have to touch the production script).
#
# One folder path per line on stdout. No side effects.

set -u

AGE_MINUTES=120

find /data/Movies /data/TV /data/Kids \
    -type f -mmin +$AGE_MINUTES \
    \( -iname '*.rar' -o -iname '*.r[0-9][0-9]' -o -iname '*.part[0-9]*.rar' \) \
    2>/dev/null \
    | while IFS= read -r rarfile; do
        dirname -- "$rarfile"
    done \
    | sort -u \
    | while IFS= read -r dir; do
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
            printf '%s\n' "$dir"
        fi
    done
