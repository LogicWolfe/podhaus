#!/bin/sh
# Maintain Sky's Restic repository on Pouch. Ofelia runs one operation per
# job; Sky's laptop only backs up and forgets its own snapshots.
set -eu

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID is required}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY is required}"

case "${1:-}" in
    check)
        set -- check
        ;;
    read-subset)
        # Reads a different tenth of the pack data each month. The month loses
        # its leading zero because shell arithmetic reads 08 as bad octal.
        year=$(date +%Y)
        month=$(date +%m)
        subset=$(( (year * 12 + ${month#0}) % 10 + 1 ))
        set -- check --read-data-subset="${subset}/10"
        ;;
    prune)
        set -- prune
        ;;
    *)
        echo "usage: maintain.sh check|read-subset|prune" >&2
        exit 64
        ;;
esac

# Jobs that land together queue here instead of failing on each other's
# exclusive repository lock.
exec 9>/tmp/sky-backups-maintenance.lock
flock 9

# Removes only locks that their owner stopped refreshing, which a live laptop
# backup does every five minutes. An abandoned laptop lock blocked every prune
# from August to September 2026.
restic unlock

# Waits out a laptop backup that still holds its lock. A first backup of a
# large tree has taken about an hour.
exec restic --retry-lock 1h "$@"
