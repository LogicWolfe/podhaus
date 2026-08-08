#!/usr/bin/env sh
# Clone LogicWolfe/nathanbaxter@main from Forgejo, build, mirror dist/
# to the nathanbaxter-com MinIO bucket. Same end state as the previous
# GitHub-based flow, just sourced from git.pod.haus (the repo moved to
# Forgejo and the GitHub copy is dead).
set -eu

: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY required}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY required}"
: "${DEPLOY_KEY_B64:?DEPLOY_KEY_B64 required}"

WORK=/tmp/source
rm -rf "$WORK"

# Read-only Forgejo deploy key (terraform/forgejo.tf), delivered
# base64-encoded via 1Password → komodo-op → Komodo Variable. SSH over
# dockernet to Forgejo's built-in listener — HTTP git is disabled
# instance-wide.
KEY=/tmp/deploy_key
umask 077
printf '%s' "$DEPLOY_KEY_B64" | base64 -d > "$KEY"

echo "==> cloning nathanbaxter@main from forgejo"
GIT_SSH_COMMAND="ssh -i $KEY -p 2222 -o StrictHostKeyChecking=accept-new" \
  git clone --depth 1 -b main \
  "git@forgejo:LogicWolfe/nathanbaxter.git" \
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
