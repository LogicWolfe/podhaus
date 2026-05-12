# Deferred follow-ups

Non-blocking items surfaced during the migration. None of these are
on the critical path — they're "do when convenient" or "do when the
upstream fix ships". Captured here so they don't drift out of memory.

## NFS bind-mount auto-recovery

Bilby-local Docker stacks bind-mount NFS paths (`/mnt/pouch` for plex
media/BIFs, paperless docs, flood torrents; `/mnt/jump` for Victoria
Logs + restic repo).

Current state has gaps:

- `/mnt/jump` is mounted but **not in `/etc/fstab`** — survives until
  first reboot, then gone.
- `/mnt/pouch` uses `_netdev,nofail` so boot continues without it and
  container bind mounts then silently resolve to empty host dirs.
- Neither mount has `x-systemd.automount` so a kangaroo reboot / network
  blip leaves the mount stale until manual remount.
- Docker daemon has no dependency on the mount units.

Investigate: systemd automount with idle timeout, docker.service
`After=` / `RequiresMountsFor=` on the mount units, per-container
restart triggers tied to mount state. Test by simulating a NAS outage
and verifying containers recover cleanly.

Affects plex, paperless, flood, logging, backup. Flagged by user
2026-04-17.

## Ofelia self-restart workaround removal

`ofelia/compose.yaml` currently has a `kill 1` daily self-restart label
that bounds stale-schedule risk to ~24h. Reason: ofelia 0.3.x in
label-discovery mode doesn't reliably react to label-value changes
when target containers are recreated — observed live during the
plex-stats-cleanup schedule shift on 2026-04-16.

Upstream [PR #368](https://github.com/mcuadros/ofelia/pull/368) "Listen
for Docker events for hot reload" has been open since July 2025. Once
it merges and ships in a release, the self-restart hack becomes
redundant.

Periodically check the PR's status + the latest `mcuadros/ofelia`
image's behaviour. When fixed, remove the daily-self-restart labels
from `ofelia/compose.yaml` and note the change in
[Scheduling](/scheduling.html).

## Bilby host-package runbook

Bilby has host packages installed ad-hoc through this migration. The
2026-05-12 working list, partially captured in
[Hosts → bilby CLI tools](/hosts.html#bilby-cli-tools):
`zellij`, `sqlite3`, `restic`, `rclone`, `railway`, `op`, `mcli`,
plus various dev tools. The `./tf` runner doesn't need a host package
(it `docker run`s `hashicorp/terraform:latest`).

Worth capturing the canonical list as a reproducible install script
(or a dnf manifest) so a fresh-bilby-from-scratch rebuild is faithful
to current state. Once scripted, link from
[Disaster recovery](/disaster-recovery.html#bilby-rebuild).

## ~~`komodo-sync` auto-deploy~~ — done 2026-05-12

`komodo-sync` now lists stacks after the second `RunSync`, compares
each stack's `info.deployed_hash` against `git rev-parse HEAD`, and
calls `DeployStack` for every stale stack. No more manual UI clicks
after editing `stack.toml` locally.

## Document Komodo orphan-container behaviour

Komodo runs `docker compose up -d` without `--remove-orphans`, so when
a service is removed from a stack's compose file the container stays
running until a human removes it. Hit twice during the migration:
paperless `Created` containers from a half-completed pre-migration
deploy, then loki when swapping to Victoria Logs.

User considered + rejected fixing at the Komodo level —
`destroy_before_deploy = true` would tear stacks down before
redeploying, more disruptive per deploy than the current cost of an
occasional manual `docker rm`.

Ongoing operational pattern: when removing a service from a stack's
compose file, manually `docker rm` the orphan after deploy. Capture
this in [Komodo](/komodo.html) or [Stack conventions](/stack-conventions.html)
as a known operational quirk so the next reader doesn't get surprised.

## `komodo-start` first-boot API-key automation

Currently the script assumes a pre-existing `Komodo API OnePassword
Sync` item in 1P that matches the running Komodo DB. On a fresh
install this is false; the manual workaround is documented in
[Disaster recovery](/disaster-recovery.html#bilby-rebuild).

Fold into `komodo-start` as an automatic first-boot path: try the
existing key, if the API call 401s, fall back to admin login + mint +
`op item edit`, then proceed.

## Upstream komodo-op Dockerfile PR

Upstream `ghcr.io/0dragosh/komodo-op` Dockerfile hardcodes
`--platform=linux/amd64` + `GOARCH=amd64`, making the multi-arch
manifest's arm64 tag a mislabelled amd64 image. Our local workaround
is `onepassword/komodo-op.Dockerfile`. Upstream fix is buildx
`BUILDPLATFORM` / `TARGETPLATFORM` args.

Low priority but polite — submit a PR upstream.

## ~~Webhook auto-deploy~~ — done 2026-05-12

GitHub webhook on `LogicWolfe/podhaus` is now managed by Terraform in
`cloudflare/github.tf`; it posts to
`komodo.pod.haus/auth/github/webhook` on every push. Cloudflare Access
bypasses the webhook path; Komodo HMAC-validates with
`KOMODO_WEBHOOK_SECRET`. Push-to-deploy is live for both bilby and
kangaroo stacks — kangaroo (Linked Repo) auto-clones the new HEAD
before deploying; bilby (`files_on_host`) deploys whatever's on its
local working tree, so push from bilby for safety. Failure alerting
routed through Gatus's `Komodo Alerts` poll → Postmark.
