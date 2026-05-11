# Completed work

Summary of everything done across the alligator → bilby migration,
organized by chunk. Specific dates and commit hashes preserved for the
ones that mattered.

## Komodo bootstrap (2026 March)

- Komodo Core deployed on bilby: postgres + ferretdb + core + periphery
  running as one stack (`komodo/ferretdb.compose.yaml`).
- 1Password Connect API + komodo-op deployed alongside; 28 Komodo
  Variables auto-populated from the Homelab vault.
- Autoheal promoted to a Komodo-managed stack.
- Environment workarounds figured out and documented: NAS-squash carve-outs
  (Jump export squashes uid 1000), SELinux on Fedora Asahi
  (`security_opt: label:disable` or `:z`), `ghcr.io/0dragosh/komodo-op`
  mislabeled arm64 manifest (local arm64 build at
  `onepassword/komodo-op.Dockerfile`), Komodo first-boot API-key dance,
  multi-line OAuth secrets don't round-trip through Komodo env files.

## Backup, logging, monitoring (2026 March – April)

- **Backrest + restic + rclone → OneDrive** end-to-end. Repo
  `857078229d` initialised at `/mnt/pouch/backups/` (later moved to
  Jump). First restore drill on `Preferences.xml` matched bit-for-bit.
  rclone sync to OneDrive completed (17.526 GiB / 1105 files).
- **Loki + Alloy + Grafana** deployed initially; **swapped to Victoria
  Logs 2026-04-16** (commit `b8a14eb`) for retention semantics and
  cheaper local storage. Grafana plugin
  `victoriametrics-logs-datasource`.
- **Uptime Kuma** scaffolded, state migrated from Railway, **then
  replaced entirely with Gatus** — config-as-code endpoint monitoring,
  Postmark alerts, push heartbeats, dead-man's-switch dashboards.

## Phase 6 architecture pivot — 2026-04-12/13

The big one. A Plex client-visible outage cascaded into a multi-day
debugging session that uncovered, in order:

1. **Wrong host timezone** (America/New_York → Australia/Perth) caused
   the Plex butler to run during peak hours.
2. **Missing theme-music DB records** triggered inline analysis under
   SQLite write locks.
3. **The real killer**: `statistics_bandwidth` in the Plex DB had
   796,867,521 rows (9 years of history, ~55 GB) with no upstream
   pruning. Offline table rebuild kept only 30 days (3,405 rows),
   followup VACUUM took ~60s, DB shrank **47 GB → 217 MB**.

Recovered by rebuilding Plex from a fresh `rsync /Jump/plex` onto local
NVMe at `/var/lib/plex-local`; BIFs switched from in-config symlink to
explicit bind. Full incident write-up in
[`/runbooks/plex-maintenance.html`](/runbooks/plex-maintenance.html).

**Design principle changed from "stateless bilby on NFS" to "local
state is the default."** Sizing rule locked in:

- Local NVMe (&lt;5 GB per stack) — hot operational state, backed up nightly.
- Jump (NAS SSD) — durable storage we'd hate to lose: restic repo, logs.
- Pouch (NAS HDD) — bulk content where capacity matters more than
  per-drive resilience.

SQLite-on-NFS is fragile under write contention; treat it as a hazard.
Autoheal + long DB ops is a bad combination — disable healthchecks +
autoheal before any planned multi-hour DB op.

## Post-pivot follow-ups — Phase 6.5

- **Backrest config-as-code** — `backup/compose.yaml` rewritten,
  state dirs bind-mounted at `/userdata/<stack>`, 9 plans staggered
  02:00–03:20 AWST (later 04:00–05:20), restic password from 1P via
  init container envsubst, `backrest-state` plan's success hook fires
  the nightly rclone sync to OneDrive. Restore drill verified
  byte-for-byte against `.rtorrent.rc`.
- **Read-only rclone.conf bug fixed** — rclone needs to rewrite its
  config in place to persist refresh tokens; changed file bind to
  writable directory bind.
- **Ofelia stack + Plex stats cleanup** — `mcuadros/ofelia:latest`
  watches Docker labels, runs `plex/scripts/stats-cleanup.sh` monthly
  to keep `statistics_bandwidth` bounded to 30 days. Self-restart label
  at 04:00 AWST until upstream PR #368 ships (label-reload-on-event).
- **Loki → Victoria Logs swap** — VL at `/mnt/jump/victoria-logs`,
  Alloy gained per-container shaping (`stage.decolorize`,
  JSON-field-rename for op-connect-api + flood).
- **Grafana dashboards** — Container Logs + Uptime Status panels
  provisioned from the repo. Grafana stripped down (drilldowns
  disabled, alerting off, marketplace hidden).
- **`/Jump/plex` deleted** — 102 GB reclaimed once the local NVMe rebuild
  proved stable.
- **Plex `/transcode`** — moved off tmpfs onto local NVMe (4 GB RAM
  reclaimed; M1 handles transcode IO trivially).
- **Plex web ingress** — added `plex.pod.haus → 172.18.0.1:32400`. Web
  only; native Plex clients still use plex.tv discovery.
- **Gatus alert richup** — Postmark body surfaces `[ALERT_DESCRIPTION]`
  + `[RESULT_ERRORS]` for triage. Backrest gained
  `CONDITION_ANY_ERROR` push so a single failed plan alerts within
  minutes instead of waiting 25h for the missing heartbeat.

## Stack migrations — Phase 7

Each followed the same rhythm: pre-migration snapshot on alligator →
stop on alligator → rsync to local bind → deploy on bilby via Komodo →
verify → add healthcheck + autoheal label → confirm Backrest plan.

- **flood** (2026-04-14) — 208 torrents rsynced from
  `flood_flood-db`; rtorrent loaded all of them from session without
  rehashing.
- **home-assistant** (2026-04-14) — 2,481 files / 81 MB rsynced;
  network_mode host preserved; HACS + victorsmartkill custom
  integrations loaded clean.
- **paperless** (2026-04-14) — pgdata + paperless-data rsynced;
  rsync's gid drift caught (999 → 986); created
  `/mnt/pouch/Paperless/`; Tika healthcheck dropped (distroless image).

## RAR auto-extract pipeline — Phase 7.5 (2026-04-20)

Config-as-code closure of the silent-extraction-failure blind spot:

- **`unpackerr/` stack** — runs as 1000:1001 so extracted files own
  the same as rtorrent's.
- **`flood/conf/rtorrent.rc`** — promoted from container-volume-only
  to repo-tracked (now bind-mounted via init container — see
  [Stack conventions](/stack-conventions.html#bind-mounts) for why no
  more single-file binds).
- **`flood/scripts/rtorrent-cleanup.sh`** — `event.download.erased`
  hook with extraction-presence guard.
- **`flood/scripts/rar-backlog.sh`** — daily ofelia job at 04:50 AWST,
  pushes Gatus heartbeat with success or failure context.
- **`rar-cleanup-scripts/` image** — one-shot remediation of the 139-
  folder legacy backlog before turning the live pipeline on. All 136
  cleanup actions recorded in
  `~/repos/podhaus-migration-state/rar-backlog-remediation.sqlite`.

## Cloudflare Tunnel cutover — Phase 8 (2026-04-14)

Executed alongside the flood migration. cloudflared on bilby
registered 4 tunnel connections; legacy alligator tunnel decommissioned
the same day.

## OneNote export — Phase 9

`hkevin01/onenote-exporter` (locally patched) extracted 1,060 OneNote
pages + 1,990 per-page asset files to
`<NFS>/Nathan/Notes Export Graph API/`. One page genuinely
unrecoverable (Graph API returns 404 for its content despite metadata
endpoint working). Patches captured at `paperless/onenote-exporter.patch`
(section-group recursion, exponential backoff, 401-mid-run handler,
per-page raw HTML save, etc.).

## Paperless bulk import — Phase 10 (2026-04-18/19)

**1,120 Paperless documents** imported across 3 batches (main import +
zip extraction + Ghostscript PDF repair). 149 canonical-page groups
cross-linked via Paperless's `document_link` custom field. 4
unsalvageable items.

Script surface in `paperless/`:
`paperless-{tag-audit,diff-plan,import,extract-zips,crosslink,repair-pdfs,wipe,finish-chain}`.

Authoritative artifacts in
`~/repos/podhaus-migration-state/paperless-imports.sqlite`. Curation
yaml + diff-plan + run logs alongside it.

See [the Paperless runbook](/runbooks/paperless.html) for the live
operating model and the [Paperless stabilization](paperless-stabilization.md)
sub-plan for the cleanup that's still open.

## Retire alligator — Phase 12 (2026-04-14)

Containers gracefully stopped during Phase 7 migrations; alligator
powered off by user after OneNote catalog + `dns/.env` extracted; UniFi
A record removed (commit `399ad7f`).

## Kangaroo bring-up + Syncthing relocation — Phases 15a + 16 (2026-05-01)

Two-server Komodo topology live:

- **`kangaroo/periphery/compose.yaml`** committed, Periphery container
  on kangaroo via Container Station with state at
  `/share/CACHEDEV1_DATA/Container/komodo-periphery/etc-komodo/`.
- **`kangaroo_bootstrap` script** at repo root, idempotent. Renders
  `.env` + `periphery.config.toml` from 1P, ships them to kangaroo,
  installs `@reboot` crontab line for Container Station / QTS upgrade
  survival, appends kangaroo to `servers.toml`.
- **`komodo/sync/repos.toml`** declares the `podhaus` Linked Repo on
  kangaroo (cloned via HTTPS + GitHub PAT — Komodo doesn't support
  SSH).
- **Syncthing** moved off bilby (where it had been a host process) to
  a Komodo-managed stack on kangaroo. New device ID
  `J7Z7LNA-…-DCXTEQD`. Tunnel ingress flipped from
  `172.18.0.1:8384` → `10.0.0.25:8384`. **Peers re-paired against the
  new device ID 2026-05-11**, all shared folders reached
  "Up to Date".
- **`kangaroo/backrest`** — separate restic repo at
  `/share/CACHEDEV2_DATA/Jump/backups-kangaroo`. Off-site OneDrive
  sync hooked into bilby's existing rclone pipeline via a read-only
  NFS view of kangaroo's repo. Three plans (syncthing /
  komodo-periphery / backrest-state) at 04:00–04:20.
- **`kangaroo/{autoheal,logging}` stacks** — autoheal restarts
  unhealthy containers on kangaroo's local Docker daemon; alloy ships
  logs cross-LAN to bilby's published Victoria Logs at
  `10.0.0.119:9428`. Gatus check on `GetServerState == "Ok"` for the
  kangaroo Periphery surfaces remote-Periphery failures as normal
  Gatus alerts.

## Terraform foundation + Cloudflare migration — 2026-05-11

End-to-end Terraform stand-up plus full migration of every Cloudflare
resource off DNSControl + the Access dashboard, in one session.

- **MinIO** (`minio/`) — single-node, dockernet-only API + loopback-
  published 9000 for `mcli`, console at `minio.pod.haus`. `mcli` RPM
  installed on bilby (`mcli` binary, Fedora rename of `mc`). Backrest
  plan + `/var/lib/minio` bind in place.
- **`tf` runner** at repo root — docker run of
  `hashicorp/terraform:latest` on dockernet, `op run` injects
  `AWS_*` + `CLOUDFLARE_API_TOKEN` from 1P.
- **Smoke test** — verified S3 backend init/apply/destroy, the
  `use_lockfile = true` S3 lock blocking concurrent applies with
  `412 PreconditionFailed`, and Backrest restic non-destructive restore
  recovering the bucket + state cleanly.
- **`cloudflare/` Terraform root** — 11 zones / 82 DNS records / 12
  Access apps / 13 policies / 1 group / 2 service tokens, zero drift.
  Per-zone `dns_<zone>.tf`, plus `access.tf` for the Zero Trust layer.
- **New Access apps** — `paperless.pod.haus` with a domain-scoped
  service-token Bypass, and a path-scoped `komodo.pod.haus/auth/github/webhook`
  app with everyone-Bypass for GitHub webhook delivery.
- **Service tokens** — *Homelab service token* (full `*.pod.haus`
  surface incl. per-host overrides) and *Paperless iOS* (scoped to
  paperless.pod.haus only). Both stored in 1P.
- **DNSControl retired for Cloudflare** — `dns/` now manages UniFi
  split-horizon only. CF API token removed from `dns/.env` and
  `dns/creds.json`. `dns-preview` / `dns-push` retained as
  UniFi-only wrappers.

Schema gotchas captured in `cloudflare/README.md`:

- SRV + URI records use `data { }` not `content`; auto-generation
  emits both and fails validation. Hand-write these.
- Top-level `priority` must be set on SRV records alongside
  `data.priority` to avoid drift.
- Imported inline (non-reusable) Access policies can't be updated via
  the provider's account-level PUT — `tf state rm` and let TF
  recreate them as reusable.
- App-launcher type apps need `landing_page_design = {}` plus
  `ignore_changes` to suppress the every-refresh `{title="Welcome!"}`
  injection.

## Documentation overhaul — 2026-05-11

- New static docs site at `https://docs.pod.haus` served by
  `docs-server/` (nginx + bind-mounted `docs/`). Tailwind v3 + a custom
  forest-green theme, auto-discovering nav from filesystem, nested
  plans support, no caching anywhere.
- `AGENTS.md` created as the canonical AI-agent instructions file;
  `CLAUDE.md` shrunk to a single `@AGENTS.md` import.
- Root `README.md` rewritten against current reality.
- `KOMODO.md`, `plex/{README,MAINTENANCE-LOG}.md` migrated into
  `docs/`; sources deleted.
- This file is the nested-plan rewrite of the original
  `alligator-bilby-migration.md`.

## All-stack arm64 compatibility

Every image except `ghcr.io/0dragosh/komodo-op` runs cleanly on arm64
as-is. komodo-op worked around with a locally-built arm64 image. Full
list: `jesec/rtorrent-flood`, `ghcr.io/ferretdb/postgres-documentdb`,
`1password/connect-api`+`connect-sync`, `garethgeorge/backrest`,
`grafana/loki`+`alloy`+`grafana`, `louislam/uptime-kuma`,
`willfarrell/autoheal`, `cloudflare/cloudflared`.
