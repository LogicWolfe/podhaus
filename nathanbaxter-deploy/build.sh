#!/usr/bin/env sh
# Clone LogicWolfe/nathanbaxter@main, build, mirror dist/ to the
# nathanbaxter-com MinIO bucket. Same end state as the previous
# .github/workflows/deploy.yml, just running inside Komodo on bilby.
set -eu

: "${GITHUB_TOKEN:?GITHUB_TOKEN required (set via OP__KOMODO__HOMELAB_GITHUB_PERSONAL_ACCESS_TOKEN__TOKEN)}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY required}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY required}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN required}"
: "${CLOUDFLARE_CACHE_ZONE:?CLOUDFLARE_CACHE_ZONE required}"
: "${CLOUDFLARE_CACHE_TAG:?CLOUDFLARE_CACHE_TAG required}"

WORK=/tmp/source
rm -rf "$WORK"

echo "==> cloning nathanbaxter@main"
git clone --depth 1 -b main \
  "https://x-access-token:${GITHUB_TOKEN}@github.com/LogicWolfe/nathanbaxter.git" \
  "$WORK"

cd "$WORK"
echo "==> HEAD: $(git rev-parse --short HEAD) ($(git log -1 --pretty=%s))"

echo "==> npm ci"
npm ci --no-audit --no-fund

echo "==> npm run build"
npm run build

echo "==> mirroring dist/ -> nathanbaxter-com bucket"
mcli alias set podhaus https://storage.pod.haus "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mcli mirror --overwrite --remove dist/ podhaus/nathanbaxter-com/

echo "==> purging Cloudflare cache tag $CLOUDFLARE_CACHE_TAG"
zone_json=$(curl -fsS \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones?name=$CLOUDFLARE_CACHE_ZONE")
zone_id=$(printf '%s' "$zone_json" | jq -er '
  if .success == true and (.result | length) == 1
  then .result[0].id
  else error("expected exactly one Cloudflare zone")
  end
')
purge_body=$(jq -nc --arg tag "$CLOUDFLARE_CACHE_TAG" '{tags: [$tag]}')
purge_json=$(curl -fsS \
  -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data "$purge_body" \
  "https://api.cloudflare.com/client/v4/zones/$zone_id/purge_cache")
if ! printf '%s' "$purge_json" | jq -e '.success == true' >/dev/null; then
  echo "Cloudflare rejected the nathanbaxter.com cache purge" >&2
  exit 1
fi

echo "==> done"
