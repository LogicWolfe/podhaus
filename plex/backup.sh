#!/bin/sh
set -eu

apk add --no-cache sqlite docker-cli >/dev/null 2>&1

DBDIR="/config/Library/Application Support/Plex Media Server/Plug-in Support/Databases"
DBFILE="$DBDIR/com.plexapp.plugins.library.db"
DEST="/pouch/backups/plex"
PENDING="$DEST/pending.db"
BACKUP="$DEST/backup.db"

log() { echo "[$(date)] $1"; }

mkdir -p "$DEST"

backup_and_verify() {
  sqlite3 "$DBFILE" ".backup '$PENDING'" 2>&1 || return 1
  result=$(sqlite3 "$PENDING" "PRAGMA integrity_check;" 2>&1 | head -1)
  [ "$result" = "ok" ]
}

restore_from_backup() {
  log "RESTORING from last known good backup..."
  cp "$BACKUP" "$DBFILE"
  rm -f "$DBFILE-wal" "$DBFILE-shm"
  log "Restarting Plex container..."
  docker restart plex
}

while true; do
  log "Starting backup..."

  if backup_and_verify; then
    mv "$PENDING" "$BACKUP"
    log "Backup verified and saved."
  else
    log "Integrity check failed. Retrying..."
    rm -f "$PENDING"

    if backup_and_verify; then
      mv "$PENDING" "$BACKUP"
      log "Retry succeeded."
    else
      rm -f "$PENDING"
      log "Retry failed — live database is corrupt."

      if [ -f "$BACKUP" ]; then
        restore_from_backup
      else
        log "ERROR: No good backup to restore from."
      fi
    fi
  fi

  sleep 86400
done
