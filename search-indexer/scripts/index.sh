#!/bin/bash
# Rebuild the Pagefind index for skycroeser-net when its HTML has changed,
# and upload it to the bucket's /_pagefind/. Run by ofelia on a schedule.
set -euo pipefail
ALIAS=sky
BUCKET="$ALIAS/skycroeser-net"
SITE=/tmp/site
STATE=/state/last-index.hash
mkdir -p "$(dirname "$STATE")"

rc alias set "$ALIAS" "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null

# Change detection: hash the HTML object listing (name+size+mtime). A
# republish updates mtimes; an unchanged bucket is skipped.
cur=$(rc object list --recursive --json "$BUCKET" | jq -ec '
  if .truncated != false then error("Incomplete object listing") else .items end
  | map(select(.key | endswith(".html"))
      | if (.size_bytes | type) == "number" and (.last_modified | type) == "string"
        then {key, size_bytes, last_modified} else error("Invalid HTML metadata") end)
  | if length == 0 then error("No HTML objects to index") else sort_by(.key) end
' | sha256sum | cut -d' ' -f1)
if [ -f "$STATE" ] && [ "$(cat "$STATE")" = "$cur" ]; then
  echo "[search-index] no HTML changes; skip"
  exit 0
fi

rm -rf "$SITE"; mkdir -p "$SITE"
rc mirror --overwrite --remove --exclude "_pagefind/*" --exclude "media/*" "$BUCKET" "$SITE" >/dev/null
pagefind --site "$SITE" --output-subdir _pagefind
rc mirror --overwrite --remove "$SITE/_pagefind" "$BUCKET/_pagefind" >/dev/null
echo "$cur" > "$STATE"
echo "[search-index] reindexed; uploaded $(find "$SITE/_pagefind" -type f | wc -l) index files"
