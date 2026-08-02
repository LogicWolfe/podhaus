#!/bin/sh
set -eu

: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"
: "${SKY_CACHE_MANIFEST_URL:?SKY_CACHE_MANIFEST_URL is required}"
: "${SKY_CACHE_ZONE:?SKY_CACHE_ZONE is required}"
: "${SKY_CACHE_TAG:?SKY_CACHE_TAG is required}"
: "${SKY_CACHE_STATE_FILE:?SKY_CACHE_STATE_FILE is required}"
: "${GATUS_BASE_URL:?GATUS_BASE_URL is required}"
: "${GATUS_HEARTBEAT_PUSH_TOKEN:?GATUS_HEARTBEAT_PUSH_TOKEN is required}"

heartbeat() {
  curl -fsS -X POST \
    -H "Authorization: Bearer $GATUS_HEARTBEAT_PUSH_TOKEN" \
    "$GATUS_BASE_URL/api/v1/endpoints/cache_sky-invalidation/external?success=true" \
    >/dev/null
}

version=$(
  curl -fsSI "$SKY_CACHE_MANIFEST_URL" |
    awk -F ': *' 'tolower($1) == "x-amz-version-id" { sub(/\r$/, "", $2); print $2 }'
)
[ -n "$version" ] || {
  echo "Sky cache manifest has no x-amz-version-id" >&2
  exit 1
}
[ "$(printf '%s\n' "$version" | wc -l)" -eq 1 ] || {
  echo "Sky cache manifest returned multiple version IDs" >&2
  exit 1
}

if [ -f "$SKY_CACHE_STATE_FILE" ] && [ "$(cat "$SKY_CACHE_STATE_FILE")" = "$version" ]; then
  heartbeat
  exit 0
fi

zone_json=$(curl -fsS \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones?name=$SKY_CACHE_ZONE")
zone_id=$(printf '%s' "$zone_json" | jq -er '
  if .success == true and (.result | length) == 1
  then .result[0].id
  else error("expected exactly one Cloudflare zone")
  end
')

purge_body=$(jq -nc --arg tag "$SKY_CACHE_TAG" '{tags: [$tag]}')
purge_json=$(curl -fsS \
  -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data "$purge_body" \
  "https://api.cloudflare.com/client/v4/zones/$zone_id/purge_cache")
if ! printf '%s' "$purge_json" | jq -e '.success == true' >/dev/null; then
  echo "Cloudflare rejected the Sky cache purge" >&2
  exit 1
fi

mkdir -p "$(dirname "$SKY_CACHE_STATE_FILE")"
printf '%s\n' "$version" >"$SKY_CACHE_STATE_FILE.tmp"
mv "$SKY_CACHE_STATE_FILE.tmp" "$SKY_CACHE_STATE_FILE"
echo "Purged $SKY_CACHE_TAG for Sky release $version"
heartbeat
