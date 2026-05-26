#!/usr/bin/env sh
# Clone LogicWolfe/nathanbaxter@main, build, mirror dist/ to the
# nathanbaxter-com MinIO bucket. Same end state as the previous
# .github/workflows/deploy.yml, just running inside Komodo on bilby.
set -eu

: "${GITHUB_TOKEN:?GITHUB_TOKEN required (set via OP__KOMODO__HOMELAB_GITHUB_PERSONAL_ACCESS_TOKEN__TOKEN)}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY required}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY required}"

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

echo "==> done"
