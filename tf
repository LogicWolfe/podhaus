#!/usr/bin/env bash
# Terraform runner. docker run hashicorp/terraform attached to dockernet
# so the MinIO state backend is reachable as `http://minio:9000`.
#
# Each TF root (e.g. `cloudflare/`, future `railway/`) owns its own `.env`
# file with op:// references for the S3 backend creds + provider creds,
# and a backend.tf pointing at `key = "<name>.tfstate"` in the shared
# `terraform-state` bucket.
#
# Usage:
#   cd cloudflare/
#   ../tf init
#   ../tf plan
#   ../tf apply
#
# Same shape as dns-push/dns-preview — op run resolves `.env` op:// refs
# into the docker run's environment, terraform reads them as standard
# AWS_*/CLOUDFLARE_* vars.

set -euo pipefail

if [[ ! -f .env ]]; then
  echo "tf: no .env in $(pwd) — each TF root needs its own .env with op:// refs" >&2
  echo "    expected at minimum: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OP_SERVICE_ACCOUNT_TOKEN="$(cat "$SCRIPT_DIR/OP_SERVICE_ACCOUNT_TOKEN")"

# Allocate a TTY only when stdin is a terminal — keeps interactive
# `terraform apply` working from a shell while still allowing the
# runner to be invoked from CI / Bash automation that lacks a TTY.
TTY_FLAGS=()
[[ -t 0 && -t 1 ]] && TTY_FLAGS=("-it")

exec op run --env-file=.env -- docker run --rm "${TTY_FLAGS[@]}" \
  --network dockernet \
  -v "$PWD:/workspace:z" \
  -w /workspace \
  -e AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY \
  -e CLOUDFLARE_API_TOKEN \
  -e UNIFI_API_KEY \
  -e GITHUB_TOKEN \
  -e TF_VAR_komodo_webhook_secret \
  hashicorp/terraform:latest "$@"
