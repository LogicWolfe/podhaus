#!/bin/bash
# Rebuild the Pagefind index for skycroeser-net when its HTML has changed,
# and upload it to the bucket's /_pagefind/. Run by ofelia on a schedule.
set -euo pipefail
ALIAS=sky
BUCKET="$ALIAS/skycroeser-net"
SITE=/tmp/site
STATE=/state/last-index.hash

mc alias set "$ALIAS" "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null

# Change detection: hash the HTML object listing (name+size+mtime). A
# republish updates mtimes; an unchanged bucket is skipped.
cur=$(mc ls --recursive "$BUCKET" 2>/dev/null | grep -E '\.html$' | sort | sha256sum | cut -d' ' -f1)
if [ -f "$STATE" ] && [ "$(cat "$STATE")" = "$cur" ]; then
  echo "[search-index] no HTML changes; skip"
  exit 0
fi

rm -rf "$SITE"; mkdir -p "$SITE"
mc mirror --overwrite --remove --exclude "_pagefind/*" --exclude "media/*" "$BUCKET" "$SITE" >/dev/null
pagefind --site "$SITE"
mc mirror --overwrite --remove "$SITE/_pagefind" "$BUCKET/_pagefind" >/dev/null
echo "$cur" > "$STATE"
echo "[search-index] reindexed; uploaded $(find "$SITE/_pagefind" -type f | wc -l) index files"
