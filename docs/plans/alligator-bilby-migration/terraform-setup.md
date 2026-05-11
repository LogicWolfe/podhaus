# Terraform foundation

**Status: complete (2026-05-11).** MinIO is live, the `tf` runner is in
place, the smoke test + restore drill passed, and
[Cloudflare as Terraform](cloudflare-terraform.md) is consuming this
state backend at `s3://terraform-state/cloudflare.tfstate`. Kept here
as the architectural record + future-tool reference.

The earlier draft of the CF plan said "local file at
`/var/lib/terraform-state/`". That works but gives up two things we'll
want sooner than expected: state locking, and a generic object-storage
surface for future tools. This plan trades a single Komodo stack
(MinIO) for both.

## State storage decision

| Option | Locking | Bootstrapping | Extra cost | Verdict |
|---|---|---|---|---|
| Local file + Backrest | None — TF will silently allow concurrent applies | Same as MinIO (restore from Backrest before TF runs) | Zero | Functional but no safety net for the "two windows open" case |
| **MinIO on bilby (this plan)** | Native S3 lockfile (TF ≥ 1.10 `use_lockfile = true`) | Restore MinIO data dir from Backrest before TF runs | One stack, one 1P item | **Picked** |
| R2 (Cloudflare-hosted S3) | Native | Bootstrapping issue — managing Cloudflare with state stored in Cloudflare | Cloudflare R2 (paid tier, small) | Rejected: rebuilding the bridge while standing on it |
| Terraform Cloud / HCP | Native, UI, history | External dependency | Free tier exists, but it's another login | Previously vetoed — keep |
| Postgres backend (reuse FerretDB pg) | Native | Trivial | Tightly couples TF state to Komodo's own DB | Rejected: weird coupling, no upside vs. MinIO |

MinIO buys us a general-purpose S3 surface. If we ever want to swap to
real S3 or R2, the backend block changes endpoint and credentials and
nothing else moves. The bootstrapping story is no worse than the
local-file plan — both depend on Backrest restoring `/var/lib/<stack>`
before TF can run.

## MinIO stack design

Single-node MinIO is fine at homelab scale. The stack runs on **bilby**
only — no need to replicate across hosts. Data dir lives on local NVMe
under the "local state is the default" rule, with Backrest covering
durability.

```
minio/
├── compose.yaml
└── stack.toml
```

Compose shape:

- Image `quay.io/minio/minio:latest`. arm64 manifest exists, no local
  build needed.
- Command: `server /data --console-address :9001`.
- Bind: `/var/lib/minio:/data` (absolute host path per the hard rules).
- Network: `dockernet`. **API port 9000 published on loopback only**
  (`127.0.0.1:9000:9000`) so bilby's host-installed `mcli` can reach
  it; console port stays internal and reaches users through the
  Cloudflare tunnel.
- Healthcheck: `curl -fSs http://localhost:9000/minio/health/live`.
- Env from Komodo Variables:
  - `MINIO_ROOT_USER=[[OP__KOMODO__MINIO_ROOT__USERNAME]]`
  - `MINIO_ROOT_PASSWORD=[[OP__KOMODO__MINIO_ROOT__CREDENTIAL]]`
  - `MINIO_BROWSER_REDIRECT_URL=https://minio.pod.haus` (only if the
    console is exposed via tunnel — see below).
- `security_opt: [label:disable]` (SELinux on Fedora Asahi).
- Autoheal label on, healthcheck-driven.

1Password item: `op://Homelab/MinIO Root` with `username` and
`credential` (40+ char random). `komodo-op` picks it up as the two
variables above.

## Console UI

Optional but recommended for ad-hoc bucket inspection. Cloudflare
Tunnel ingress:

```yaml
- hostname: minio.pod.haus
  service: http://minio:9001
```

DNS CNAME for `minio.pod.haus` in `dns/dnsconfig.js`. The existing
`*.pod.haus` Cloudflare Access wildcard gates it on the Family
policy — no new Access app needed.

## Bucket and user layout

MinIO Client is installed locally on bilby as `mcli` — the binary lives
at `/usr/local/bin/mcli` from the upstream RPM
(`sudo dnf install https://dl.min.io/client/mc/release/linux-arm64/mc.rpm`).
The Fedora package is named `mcli` to avoid colliding with Midnight
Commander. Upstream MinIO docs uniformly say `mc`; mentally substitute.
See [Hosts](/hosts.html#bilby-cli-tools) for the broader local-CLI
pattern.

One-shot bootstrap via bilby's local `mcli` against the loopback-only
API port:

```sh
op run --env-file=<(echo "
MINIO_ROOT_USER=op://Homelab/MinIO Root/username
MINIO_ROOT_PASSWORD=op://Homelab/MinIO Root/credential
") -- bash -c '
  mcli alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" &&
  mcli mb --with-versioning local/terraform-state &&
  mcli admin user add local terraform "$(openssl rand -base64 30)" &&
  mcli admin policy attach local readwrite --user terraform
'
```

`mcli admin user add` prints the generated secret — capture it and
store it in 1P as `op://Homelab/MinIO Terraform User` immediately,
before it scrolls out of view.

- **Bucket**: `terraform-state` with **versioning enabled** so an
  accidental `terraform destroy` leaves the previous state version
  recoverable.
- **Object key per tool**: `cloudflare.tfstate`, room for
  `railway.tfstate` etc. later.
- **Dedicated TF user** (don't use root): `mcli admin user add local
  terraform <generated-secret>` plus a `readwrite` policy scoped to
  `arn:aws:s3:::terraform-state/*`. Save credentials to
  `op://Homelab/MinIO Terraform User`.

Root credentials are for stack management only. Day-to-day TF runs use
the policy-bound user. The console UI at `minio.pod.haus` is the
hands-on path for ad-hoc browsing; `mcli` against `127.0.0.1:9000` is
the scriptable one.

## Backend config

```hcl
terraform {
  required_version = ">= 1.10.0"
  backend "s3" {
    endpoint                    = "http://minio:9000"
    bucket                      = "terraform-state"
    key                         = "cloudflare.tfstate"
    region                      = "us-east-1"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    use_lockfile                = true
    encrypt                     = false
  }
}
```

`use_lockfile = true` is the post-1.10 way to do locking without a
separate DynamoDB sidecar — TF writes a `.tflock` object next to the
state with conditional-put semantics. MinIO supports this.

`encrypt = false` because the bucket is on the LAN and the data dir
sits on a Backrest-encrypted-at-rest path anyway. Revisit if MinIO
ever gets exposed to the open internet.

## Runner wrapper

A `tf` script at the repo root, same shape as `dns-push` /
`dns-preview`:

```sh
#!/usr/bin/env bash
set -euo pipefail
exec docker run --rm -it \
  --network dockernet \
  -v "$PWD:/workspace" -w /workspace \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
  -e CLOUDFLARE_API_TOKEN \
  hashicorp/terraform:latest "$@"
```

The runner attaches to **`dockernet`** so it can reach `minio:9000` by
container name. Credentials are populated by `op run -- ./tf …`
reading from 1P:

- `AWS_ACCESS_KEY_ID` ← MinIO Terraform User username
- `AWS_SECRET_ACCESS_KEY` ← MinIO Terraform User credential
- `CLOUDFLARE_API_TOKEN` ← `op://Homelab/Cloudflare API Token` (only
  needed for CF runs)

Usage:

```sh
op run -- ./tf init
op run -- ./tf plan
op run -- ./tf apply
```

No `tf-plan` / `tf-apply` aliases yet — keeping the surface minimal.
Add wrappers if the `op run` prefix becomes annoying.

## Backup plan

New Backrest plan `minio`, snapshots `/var/lib/minio`. Schedule co-
located with the existing 04:00 window. Retention can match the other
small-state plans (`14 daily + 4 weekly + 6 monthly`).

State volume is small (KB per `.tfstate`), so snapshot cost is
negligible. Backrest's nightly rclone hook ships the snapshots to
OneDrive — same off-site pipeline every other stack uses.

## Setup steps

1. **Create 1P items**:
   - `MinIO Root` (`username`, `credential`).
   - `MinIO Terraform User` (`username`, `credential`) — created in
     step 6 below; 1P entry seeded with placeholder, filled after
     `mc admin user add`.
2. **Add `minio/{compose.yaml, stack.toml}`** following the
   single-host stack template in
   [Stack conventions](/stack-conventions.html).
3. **Add the Backrest plan** in `backup/bilby/config.json.tmpl` for
   `/var/lib/minio` — same 04:00-window pattern as the others.
4. **`./komodo-sync`**, deploy MinIO from the Komodo UI. Wait for
   healthy.
5. **Create the bucket** via the `mc` one-shot (see "Bucket and user
   layout" above). Confirm versioning with
   `mc version info local/terraform-state`.
6. **Create the TF user + policy** via `mc admin user add` and
   `mc admin policy attach`. Save credentials to 1P.
7. **(Optional)** Add `minio.pod.haus` ingress in
   `cloudflare-tunnel/conf/config.yml` and a CNAME in
   `dns/dnsconfig.js`; `./dns-push`. Browser-test the console UI.
8. **Write the `tf` runner** at the repo root, `chmod +x`.
9. **Smoke test** — create a throwaway `terraform-smoke/` directory
   with a single `null_resource`, write the backend block above
   (with `key = "smoke.tfstate"`), `op run -- ../tf init` then
   `apply`. Confirm:
   - `smoke.tfstate` lands in MinIO (visible in the console).
   - A concurrent `apply` from a second shell **blocks on the
     lockfile** rather than racing.
   - `mc ls local/terraform-state --versions` shows the state
     versions.
   - Remove the smoke directory + state once verified.
10. **Restore drill** — stop MinIO, delete `/var/lib/minio`,
    restore from the latest Backrest snapshot, restart MinIO,
    confirm `op run -- ./tf init` still finds the state. Same
    cadence as the Plex restore drill.

## Open questions

- **TZ on the MinIO container** — does MinIO log times in UTC by
  default? Set `TZ` from the standard `${TZ}` Komodo Variable for
  consistency with every other stack.
- **MFA on root account** — MinIO supports MFA for the console UI;
  worth enabling if the console ends up exposed. Out of scope for the
  initial bring-up.
- **Object-lock vs versioning** — versioning is enough for state-file
  rollback. Object lock adds compliance-style immutability we don't
  need at this scale.

## Out of scope

- Multi-node / distributed MinIO. Single-node is correct for this
  workload.
- Migrating other state into MinIO (Komodo's pgdata, Loki/VL data,
  etc.). Those have their own durability stories already.
- Public-facing S3 endpoint for external tooling.
- Other future tenants of this MinIO (image cache, ad-hoc blob,
  Velero, container registry) — noted as possibilities, not part of
  this plan.

## Reference

- TF S3 backend with native lockfile (no DynamoDB):
  <https://developer.hashicorp.com/terraform/language/backend/s3#use_lockfile>
- MinIO docker reference:
  <https://min.io/docs/minio/container/index.html>
- `mc` admin commands:
  <https://min.io/docs/minio/linux/reference/minio-mc-admin.html>
