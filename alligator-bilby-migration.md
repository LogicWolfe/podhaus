# Alligator → Bilby Migration

Migration of all running services from `alligator` (Intel NUC, x86_64, Linux) to `bilby` (Apple Silicon M1 Mac mini running Asahi Linux, aarch64). Bilby is the new home of the `podhaus` deployment. Once complete, alligator is retired.

## Resumption pointer (read this first if returning to a fresh session)

**Current state:** planning complete, zero code changes made, zero containers touched. All architectural decisions locked. Credentials are the only blocker for execution.

**Next action when resuming:**

1. User completes the rclone OneDrive OAuth dance (see "rclone provisioning runbook" below) and stashes the result in 1Password Homelab as `rclone-onedrive-token`.
2. Begin phase 1 (pre-flight cleanup) — credential-free, all local file edits.
3. Proceed through phases 2–13 in order.

**Credentials status:** `railway-api-token` ✓, `postmark-smtp` ✓, `restic-repo-password` ✓, `rclone-onedrive-token` ✓.

## Context

- **alligator**: i5-8259U, 8 threads, 7.6 GB RAM. Running all current podhaus services under a local Komodo Core. Swapping heavily (2 GB swap full).
- **bilby**: Apple M1, 8 cores, 15 GB RAM, arm64. Already running `plex` + `plex-backup` standalone (outside Komodo). Target host for everything.
- Both machines mount the kangaroo NAS (`10.0.0.25`) — alligator at `/mnt/NFSPouch`, bilby at `/mnt/pouch`.
- **kangaroo NAS storage layers**: Pouch is on 5 spinning HDDs (29 TB, ~5.2 TB free). Jump is on 2 SATA SSDs (382 GB total, currently ~102 GB used by plex config, ~280 GB free). Same host, different drives, different RAID arrays. **Throughput is equivalent** between the two (both CPU-limited on the NFS controller), but **Jump has massively better IOPS**. Rule: latency-sensitive workloads → Jump; bulk/throughput workloads → Pouch.

## Current state on alligator

### Docker stacks (all managed by alligator's Komodo Core)

| Stack | Containers |
|---|---|
| `komodo` | komodo-core, komodo-periphery, komodo-postgres, komodo-ferretdb |
| `onepassword` | op-connect-api, op-connect-sync, komodo-op |
| `cloudflare-tunnel` | cloudflare-tunnel |
| `flood` | flood |
| `home-assistant` | home-assistant (`network_mode: host`) |
| `paperless` | paperless, paperless-postgres, paperless-redis, paperless-tika, paperless-gotenberg |

### Host-level services on alligator

- `syncthing@nathan` (host) — ports 22000 / 8384. Routed via `sync.pod.haus`. **Decision: defer to post-migration, likely relocate to the NAS host.**
- `tailscaled` — needed on bilby (install separately, not part of this migration).
- `go2rtc` (host binary, port 18555) — **Decision: abandon, not moving.**
- Python process on `10.0.0.83:1400` — identified as Home Assistant itself (Sonos SOAP port, host-networked).

### Container state to migrate (source volumes)

Pulled across to bilby as part of each stack migration. All live on alligator's local disk today.

| Volume | Size | New home on bilby |
|---|---|---|
| `home-assistant_home-assistant-config` | 86 MB | `/Jump/home-assistant/` |
| `paperless_paperless-pgdata` | 69 MB | `/Jump/paperless/pgdata/` |
| `paperless_paperless-data` | 16 MB | `/Jump/paperless/data/` |
| `flood_flood-db` | 16 MB | `/Jump/flood/db/` |
| `paperless_paperless-media` | 20 KB (nearly empty) | bind mount to Pouch (docs belong there, not Jump) |

### Cloudflare tunnel ingress (current)

Tunnel ID `cc68c7c9-1dad-42aa-af04-46119d3e515f`, credentials in 1Password.

| Hostname | Target |
|---|---|
| `komodo.pod.haus` | `http://komodo-core:9120` |
| `torrent.pod.haus` | `http://flood:3000` |
| `home.pod.haus` | `http://172.18.0.1:8123` (HA on host network) |
| `kangaroo.pod.haus` | `http://10.0.0.25:8080` (NAS, external) |
| `sync.pod.haus` | `http://172.18.0.1:8384` (Syncthing on host) — will drop |
| `unifi.pod.haus` | `https://10.0.0.1:443` (UniFi, external) |
| `paperless.pod.haus` | `http://paperless:8000` |

## Storage and recovery architecture

### Design principles

- **Bilby is stateless.** Every piece of container state lives on the NAS so the Mac mini can be reimaged without data migration.
- **State in one place.** No creeping local volumes; no "just this one thing on local disk" exceptions.
- **Tight storage on the host.** The M1's internal SSD is small and non-upgradable. Resisting creep matters.
- **Single-client, low-load assumptions.** We're not running production multi-tenant workloads. Anti-patterns that bite at scale (postgres-on-NFS, SQLite-on-NFS) are acceptable here with good backups.

### Layout conventions

**Jump (`10.0.0.25:/Jump`, SSD, 382 GB)** — container state only. ~0.1 ms operation latency. SSD IOPS is the reason everything latency-sensitive (databases, config files, anything with small-random access patterns) lives here.

- `/Jump/<container>/` — per-container state directory. Subdirs for multi-volume containers (e.g. `/Jump/paperless/{pgdata,data}`, `/Jump/komodo/{postgres,ferretdb}`).
- Container state as Docker NFS volumes (driver_opts: `type: nfs, o: addr=10.0.0.25,nfsvers=4.1,soft,timeo=600,retrans=5,rw`, async).

**Pouch (`10.0.0.25:/Pouch`, HDD, 29 TB)** — bulk media + backups. Spinning disks, throughput matches Jump but IOPS are much lower. Anything big and sequential belongs here (restic repo chunks, paperless archive, plex media).

- Bulk media bind mounts: paperless archive, flood downloads, plex libraries, etc.
- Backup directory: **TBD on exact path** — candidates are `/mnt/pouch/Backups/podhaus/` or `/mnt/pouch/podhaus/backups/`.

**Local bilby disk** — docker daemon, image cache, container logs (with size caps). No persistent state.

### Mount options

- `soft,timeo=600,retrans=5` — fails with EIO after ~5 min of NAS unresponsiveness rather than hanging forever. Containers crash, autoheal restarts them, Docker re-mounts fresh when NAS is back.
- **Async** — user has benchmarked and confirmed sync writes materially hurt performance. Durability gap (up to a few seconds of uncommitted writes on a crash) is acceptable given the "24h of loss is tolerable" risk appetite.

### Healthcheck pattern

Copy plex's shape (`plex/healthcheck.sh`): HTTP API probe **plus** `ls` on each NFS-backed mount the container uses. The `ls` catches stale NFS handles that a pure HTTP check would miss.

```sh
#!/bin/sh
set -e
curl -sf http://localhost:<PORT>/<PATH> > /dev/null
ls /<nfs-mount-1> > /dev/null
ls /<nfs-mount-2> > /dev/null
```

### Auto-recovery chain

```
NAS flaps → I/O errors → healthcheck fails (HTTP or ls check)
          → autoheal restarts container
          → Docker re-mounts NFS on start
          → if NAS still down, container exits, restart: unless-stopped retries
          → NAS returns → mount succeeds → container healthy
```

### Docker log driver caps

Docker daemon config on bilby sets `log-driver: local` with `max-size=50m`, `max-file=3` to prevent log growth from consuming local disk. Belt and braces alongside any centralised log solution.

### Backup strategy

**Stack:**

- **Backrest** (`garethgeorge/backrest`) — orchestrator. Web UI, scheduling, pre/post hooks, operation history, browsable restore. Wraps restic natively. Deployed as its own Komodo stack.
- **Restic** — storage engine (Backrest shells out to it).
- **Rclone** — OneDrive backend for off-site sync (separate Backrest hook or scheduled step).
- **Shoutrrr** (built into Backrest) → Postmark SMTP for backup notifications.
- **Custom pre-hook script** — the small unavoidable custom piece. Handles DB dumps, integrity validation, and on SQLite integrity failure pulls the last known-good copy via `restic dump` and restores the live DB before the backup proceeds.

**Considered and rejected:**

- **pgBackRest** for postgres: genuinely excellent postgres tool with PITR, WAL archiving, native verification. Rejected because PITR is the only meaningful value-add at our scale and the cost (second repo, second config, second notification path, second runbook) is not worth the 24h-of-data-loss insurance for single-client low-load paperless/komodo workloads. 24h loss is acceptable; we re-OCR documents if needed.

**Shape: local Pouch repo + rclone sync to OneDrive.**

1. Backrest runs a scheduled backup daily.
2. Pre-hook (custom script) dumps all databases to a staging directory: `pg_dump` for paperless-postgres/komodo-postgres, `sqlite3 .backup` for HA / plex library db / onenote catalog.
3. Pre-hook validates each dump: postgres via `pg_restore --list` smoke test, SQLite via `PRAGMA integrity_check`. Retries up to 3× with 10s backoff on validation failure.
4. On final SQLite validation failure: pre-hook pulls last known-good from `restic dump latest --tag <container> --path <db>`, restores the live DB, restarts the container, logs + alerts, and continues the backup run.
5. On final postgres validation failure: pre-hook aborts the backup run (don't overwrite the last-good snapshot history with a known-bad state), alerts loudly. Manual recovery from restic.
6. Restic (via Backrest) backs up `/Jump` + staging dumps to the Pouch repo, tagged per container.
7. Separate Backrest step: `rclone sync` the Pouch repo to OneDrive for off-site DR.
8. Notifications go through Shoutrrr → Postmark SMTP on any success-with-retries, failure, or auto-restore event.

**Retention**: 14 daily + 4 weekly + 6 monthly snapshots. Restic handles pruning automatically.

**What gets backed up:** everything in `/Jump` (unfiltered). Plex metadata stays in the backup for now — exclusion is deferred until we've validated plex metadata is actually regeneratable on this setup (current experience says it isn't reliable). If validated later, excluding plex cache/metadata reclaims ~100 GB of repo space.

**Failure coverage:**
| Failure | Protection |
|---|---|
| Bilby dies | Reimage, clone repo, `komodo-start`. All state on NAS — nothing to restore. |
| SSD (Jump) corruption or RAID loss | Restore from Pouch restic repo (different drives). |
| NAS OS / ZFS pool / kangaroo hardware loss | Restore from OneDrive via rclone. |
| Disaster (fire, theft) | OneDrive is off-site. |
| Single-file oops | `restic restore` from most recent snapshot. |
| Database corruption from NFS crash mid-write | Restore from previous day's snapshot (dump-based). Lose at most 24h. |

**Non-negotiable gate:** backup stack must be deployed, first snapshot taken, and at least one restore dry-run completed against a scratch target **before** any database-backed stack (paperless, komodo-postgres) is migrated to bilby and pointed at Jump.

### Storage projections

| Location | Capacity | 1-yr projection | Headroom |
|---|---|---|---|
| Jump (SSD) — container state | 382 GB | ~137 GB | ~245 GB |
| Pouch (HDD) — restic repo | ~5.2 TB free | ~150 GB (full plex included) | ~5 TB |
| OneDrive — rclone target | 1 TB quota | ~150 GB | ~850 GB |

Jump expansion requires new hardware (2 bays available). Not a near-term concern.

## Key decisions

- **Reuse tunnel credentials** — do not create a new Cloudflare tunnel. Hot-swap cloudflare-tunnel stack from alligator to bilby at cutover.
- **`MEDIA_DIR` → `/mnt/pouch`** on bilby (match existing bilby NFS mount; update `komodo/sync/variables.toml` and any compose files that hardcode `/mnt/NFSPouch`).
- **Drop `go2rtc`** — not moving.
- **Syncthing** — defer. Likely relocate to NAS host after this migration wraps. Drop `sync.pod.haus` ingress rule during cutover.
- **Autoheal via `willfarrell/autoheal`** — Komodo has no native auto-restart (issue #531 still open), and Docker doesn't restart on healthcheck failures. Use `AUTOHEAL_CONTAINER_LABEL: autoheal` (opt-in via label, not `all`). Convert the orphan `autoheal/` compose into a proper Komodo stack.
- **OneNote exporter fresh clone** — `hkevin01/onenote-exporter` is not a fork, working tree clean on alligator. Fresh clone on bilby, bring SQLite catalog + token cache.
- **Untracked paperless scripts** on alligator (`export-*.sh`, `index-*.sh`, `onenote-export`) → pull into the repo and commit before execution.
- **Commit strategy**: commit directly to `main` as each step lands. No long-running migration branch, no per-phase PRs.
- **All container state on NFS (Jump)**, async mount. Bilby is stateless. Databases run on NFS despite the general anti-pattern — single-client low-load use case.
- **Backups via restic → Pouch repo → rclone sync to OneDrive.** One tool, layered destinations, covers SSD/NAS/disaster failure modes independently.
- **Plex metadata included in backups** for now. Exclusion is a future experiment conditional on validating regeneration works.
- **Retention**: 14 daily + 4 weekly + 6 monthly restic snapshots.
- **Healthcheck pattern**: HTTP API probe + `ls` each NFS mount (copy plex's `healthcheck.sh` shape).
- **Docker log driver caps**: `local` driver with `max-size=50m`, `max-file=3`. Prevents log growth from undermining the stateless-machine goal.
- **Backup-first gate**: no database stack is migrated to bilby until backup infrastructure is deployed, snapshotted, and restore-tested.
- **Paperless document archive** lives at `/mnt/pouch/Paperless/`, bind-mounted into the paperless container as the media root. Documents themselves on HDD Pouch; paperless's search index and pgdata stay on Jump.
- **Logging**: Loki + Grafana Alloy + Grafana, as a new Komodo stack. Alloy scrapes all containers via docker socket (no per-container config). Loki storage at `/Jump/loki/` with retention via compactor (default 30 days). Grafana exposed via new `logs.pod.haus` ingress. Kept alongside `log-driver: local` caps as belt-and-braces.
- **Autoheal label list** — the only real reason to skip is cascade risk from restarting the orchestrator itself. Everything else benefits.
  - Include (`autoheal=true`): `plex`, `paperless`, `paperless-postgres`, `paperless-redis`, `paperless-tika`, `paperless-gotenberg`, `flood`, `home-assistant`, `cloudflare-tunnel`, `op-connect-api`, `op-connect-sync`, `komodo-op`
  - Skip: `komodo-core`, `komodo-periphery`, `komodo-postgres`, `komodo-ferretdb` (orchestration layer — autoheal loops here could interrupt in-flight deployments; `restart: unless-stopped` handles genuine crashes), `plex-backup` (long-sleeping cron pattern, no meaningful healthcheck), `autoheal` (can't heal itself).
  - **Healthcheck additions required**: `paperless-tika`, `paperless-gotenberg`, `cloudflare-tunnel`, `op-connect-api`, `op-connect-sync`, `komodo-op`. Autoheal is a no-op on containers without a `HEALTHCHECK`, so these need new healthchecks as part of the migration.
- **Restic repo layout**: single repo at `/mnt/pouch/backups/` (top-level, no nesting), per-container tags on backup (`restic backup --tag <container> /Jump/<container>`). Restores filter by tag. One password, one schedule, logical per-container isolation where it matters. Existing `/mnt/pouch/backups/plex/` directory is stale from the retired plex-backup container and gets cleaned up during phase 3.
- **Backup orchestration**: **Backrest** wraps restic as the scheduler, hook runner, UI, and notification layer. Avoids writing custom cron + wrapper glue. Deployed as its own Komodo stack.
- **pgBackRest rejected**: genuinely great postgres tool but the PITR/WAL-archiving value isn't worth the cost of maintaining a second backup system at our scale. 24h of data loss is acceptable.
- **Retire `plex-backup` container**: its functionality (SQLite dump + integrity check + auto-restore on corruption) rolls into the restic pre-hook wrapper, extended to cover HA's SQLite and onenote catalog as well. Delete `plex/backup.sh` and the `plex-backup` service from `plex/compose.yaml`.
- **Validate-and-maybe-restore pattern** in the pre-hook wrapper:
  - SQLite (`plex`, `home-assistant`, `onenote-exporter` catalog): dump via `sqlite3 .backup`, verify with `PRAGMA integrity_check`, retry 3× with 10s backoff. On final failure, auto-restore from `restic dump latest --tag <container>`, restart container, continue backup. Alert on any retry.
  - Postgres (`paperless-postgres`, `komodo-postgres`): dump via `pg_dump --format=custom`, verify with `pg_restore --list`, retry 3× with 10s backoff. On final failure, abort the backup run and alert. No auto-restore (too destructive to automate for postgres).
- **Notifications**: Postmark via SMTP. Backrest uses built-in Shoutrrr (SMTP transport). Komodo Alerter uses a custom HTTP endpoint routed through a small relay (Apprise or similar) to the same Postmark SMTP. Uptime Kuma uses its native SMTP notifier. One destination, three sources (backup events, container health, external reachability + heartbeat).
- **Uptime Kuma** — deployed as a Komodo stack on bilby, state at `/Jump/uptime-kuma/`, exposed via `uptime.pod.haus`. Migrated from the existing Railway-hosted instance using the full-state option (SQLite DB copy via Railway CLI), preserving monitor configs, notification configs, and history.
- **Encryption**: restic repository is encrypted. Password (`restic-repo-password`) lives in 1Password Homelab vault, surfaced as a Komodo Variable. The 1Password Emergency Kit hardcopy (fire-safe) gets an annotation noting the password location.

## OneNote export status (to be resumed on bilby)

Using `hkevin01/onenote-exporter` via Microsoft Graph API. Output lives at `<NFS>/Nathan/Notes Export Graph API/` — accessible from either host. Progress as of survey:

| Notebook | Pages planned | Pages exported | Status |
|---|---|---|---|
| Blue Sky Trust | 4 | 4 | Complete |
| Family Life | 10 | 10 | Complete |
| Financial | 8 | 7 | 1 short |
| Fractal Seed | 14 | 14 | Complete |
| Immigration Stuff | 24 | 24 | Complete |
| Interesting Designs | 51 | 51 | Complete |
| **Life** | **894** | **452** | **~51%, in flight** |
| Nathan's Notebook | 5 | 5 | Complete |
| Orijin Plus | 18 | 18 | Complete |
| Pod Foundation | 22 | 22 | Complete |
| Property | 20 | 20 | Complete |
| Shadow | 1 | 1 | Complete |
| Sky | 25 | 25 | Complete |
| Switch | 9 | 9 | Complete |
| Travel | 6 | 6 | Complete |

**Total: 668 / 1,111 pages exported**, ~1.2 GB on NFS. Remaining work is ~442 pages of Life plus the stray Financial page. Exporter is incremental (SQLite catalog) so resuming is safe.

Phase 3 of `paperless/onenote-to-paperless.md` (the upload script that walks the export tree and pushes to Paperless) is still unwritten.

## Migration phases

### 1. Pre-flight cleanup (no services touched yet)

- [ ] Update `komodo/sync/variables.toml`: `MEDIA_DIR = /mnt/pouch`
- [ ] Update `flood/compose.yaml`: replace hardcoded `/mnt/NFSPouch` with `${MEDIA_DIR}`, switch `flood-db` from local volume to NFS volume at `/Jump/flood/db/`
- [ ] Pull untracked paperless scripts from alligator into this repo (`paperless/export-life.sh`, `export-remaining.sh`, `index-all.sh`, `index-life.sh`, `onenote-export`)
- [ ] Convert `autoheal/` into a proper Komodo stack (`stack.toml`, change label mode to opt-in)
- [ ] Audit healthchecks across compose files; document which containers will get `autoheal=true` labels
- [ ] Set Docker daemon log driver caps (`log-driver: local`, `max-size=50m`, `max-file=3`) on bilby
- [ ] Convert all remaining compose volumes from local to NFS-backed (`/Jump/<container>/...`): paperless, home-assistant, komodo, onepassword
- [x] Decide on commit/PR strategy with user — commit directly to `main` as each step lands

### 2. Bootstrap Komodo on bilby (infra only, no stateful stacks yet)

- [ ] Run `./komodo-start` — brings up komodo-core, postgres, ferretdb, periphery, 1Password Connect, komodo-op
- [ ] Verify 1Password vault `hjpenq2avoprqh2u3hqxap3jjq` syncs into Komodo Variables
- [ ] Verify bilby's Komodo Core can reach its local periphery and deploy a test stack
- [ ] Verify komodo-postgres + komodo-ferretdb recover gracefully from a cold start while NFS is briefly unavailable (simulate)

### 3. Backup infrastructure (before any DB stack migrates)

- [ ] Clean up stale `/mnt/pouch/backups/plex/` directory (plex-backup is being retired)
- [ ] Create `backup/compose.yaml` + `stack.toml` — Backrest container, volumes for `/Jump` (read) and `/mnt/pouch/backups/` (write), mounted pre-hook script directory
- [ ] Write pre-hook wrapper script: per-DB dump + `PRAGMA integrity_check`/`pg_restore --list` validation, 3× retry with 10s backoff, auto-restore from `restic dump latest` on SQLite failure, abort + alert on postgres failure
- [ ] Retire `plex-backup` service from `plex/compose.yaml`, delete `plex/backup.sh`
- [ ] Initialise encrypted restic repo at `/mnt/pouch/backups/` (password from 1Password via Komodo Variable)
- [ ] Configure rclone with OneDrive backend (token from 1Password)
- [ ] Wire Backrest → Shoutrrr → Postmark SMTP for backup event notifications
- [ ] Run first full snapshot (just against `/Jump/plex/` initially — only state present on Jump at this point)
- [ ] Run rclone sync to OneDrive; confirm first-upload size and integrity
- [ ] **Restore drill**: `restic restore latest --tag plex --target /tmp/restore-test`, verify a known file matches source, delete scratch
- [ ] Schedule nightly backup + nightly rclone sync via Backrest

### 4. Logging infrastructure

- [ ] Set Docker daemon log driver caps (`local` driver, `max-size=50m`, `max-file=3`)
- [ ] Create `logging/compose.yaml` + `stack.toml` — Loki + Grafana Alloy + Grafana
- [ ] Loki storage at `/Jump/loki/`, retention configured via Loki compactor (30 days)
- [ ] Alloy scrapes all local containers via docker socket
- [ ] Grafana exposed via new `logs.pod.haus` ingress rule in cloudflare-tunnel compose
- [ ] Seed Grafana with a basic "all container logs" dashboard
- [ ] Verify logs from existing plex container are flowing

### 5. Uptime Kuma migration from Railway

Preserves monitor configs, notification configs, and history via SQLite volume copy.

- [ ] Install `railway` CLI on bilby (or run via container)
- [ ] Authenticate with `railway-api-token` from 1Password
- [ ] Identify the Kuma project + service + volume in Railway
- [ ] Create `uptime-kuma/compose.yaml` + `stack.toml` on bilby, state dir `/Jump/uptime-kuma/`, port 3001
- [ ] Stop Railway Kuma briefly OR use `sqlite3 .backup` for consistent live copy
- [ ] `railway ssh` / `railway run` into Kuma container, `sqlite3 /app/data/kuma.db .backup /tmp/kuma-snapshot.db`, copy it out
- [ ] Copy `kuma.db` and any other `/app/data` contents into `/Jump/uptime-kuma/` on bilby
- [ ] Deploy local Kuma stack via Komodo
- [ ] Verify all monitors, notification configs, users restored correctly
- [ ] Add `uptime.pod.haus → http://uptime-kuma:3001` to `cloudflare-tunnel/compose.yaml` ingress
- [ ] Update `dns/dnsconfig.js` — remove the Railway CNAME for `uptime`, let the tunnel handle it (match the pattern used by other `*.pod.haus` hosts)
- [ ] `dns-push` to apply
- [ ] Verify `uptime.pod.haus` resolves to the new local instance
- [ ] Add Docker container monitors in Kuma for each existing bilby container (plex, backrest, loki, etc.)
- [ ] Add HTTP monitors for every `*.pod.haus` endpoint
- [ ] Wire Backrest push-monitor URL into backup hooks (Kuma alerts on missing heartbeat)
- [ ] Decommission Railway Kuma project (keep for 72h as rollback safety, then delete)

### 6. Arm64 compatibility spot-check

Pull-test these on bilby before deploying stacks — everything else in the inventory is known-good multi-arch:

- [ ] `jesec/rtorrent-flood`
- [ ] `ghcr.io/0dragosh/komodo-op` (covered in phase 2 — will fail fast if no arm64)
- [ ] `ghcr.io/ferretdb/postgres-documentdb`
- [ ] `restic/restic`, `rclone/rclone`, `garethgeorge/backrest` (phase 3)
- [ ] `grafana/loki`, `grafana/alloy`, `grafana/grafana` (phase 4)
- [ ] `louislam/uptime-kuma` (phase 5)

### 7. Stack migrations (smallest blast radius first)

For each stack: take a pre-migration snapshot on alligator → stop on alligator → rsync volume(s) into the new NFS path under `/Jump/<container>/` → deploy on bilby via Komodo → verify → add healthcheck + autoheal label as part of the same change → confirm next backup run captures the new state → add Kuma monitors for the new container.

- [ ] **flood** — rsync `flood_flood-db` → `/Jump/flood/db/` (16 MB). Add healthcheck `curl -f http://localhost:3000/api/` + `ls /flood-db` + `ls /data`.
- [ ] **paperless** — rsync `paperless-data` → `/Jump/paperless/data/`, `paperless-pgdata` → `/Jump/paperless/pgdata/` (~85 MB total). Mount paperless media as a bind mount from `/mnt/pouch/Paperless/`. Redis/Tika/Gotenberg stateless. Add healthchecks to tika + gotenberg (needed for autoheal). Add healthcheck to main `paperless` container.
- [ ] **home-assistant** — rsync `home-assistant-config` → `/Jump/home-assistant/` (86 MB). Verify integrations reconnect after host change (Sonos, any LAN-bound devices). Add healthcheck.

### 8. Cloudflare tunnel cutover

Reusing tunnel credentials means both hosts can't run cloudflared simultaneously. Hot swap:

- [ ] Confirm flood/paperless/HA are running on bilby and stopped on alligator
- [ ] Drop `sync.pod.haus` ingress rule (syncthing deferred)
- [ ] Deploy `cloudflare-tunnel` stack on bilby while stopping it on alligator (coordinated cutover)
- [ ] Verify all `*.pod.haus` routes still resolve

### 9. Finish OneNote export on bilby

- [ ] Clone `hkevin01/onenote-exporter` fresh on bilby
- [ ] Copy SQLite catalog from alligator: `~/repos/onenote-exporter/cache/db/catalog.sqlite`
- [ ] Copy token cache (or re-auth via device code flow)
- [ ] Build exporter image on bilby
- [ ] Run `./paperless/export-remaining.sh` to finish Life + chase the stray Financial page
- [ ] Verify final page counts match plan

### 10. Paperless upload (Phase 3 of onenote-to-paperless.md)

- [ ] Write upload script — walks export tree, uploads via `POST /api/documents/post_document/`, tags by notebook + section
- [ ] Dry-run against one small notebook (Shadow? Travel?)
- [ ] Full import
- [ ] Verify in Paperless UI: tag counts, sample search, spot-check attachments

### 11. Railway migrations: doggos and yiayia

Two additional Railway-hosted services that need to come local. Survey first, plan second, execute third. Done after the Cloudflare tunnel cutover so all local tunnel routing is stable before we start reshuffling DNS for these.

- [ ] Survey the Railway projects via `railway` CLI: image, env vars, volumes, exposed ports, any persistent state
- [ ] Document what each service actually is (`doggos.indigo.pod.haus` and `yiayia.pod.haus`) — purpose, dependencies, data sensitivity
- [ ] Create `doggos/` and `yiayia/` directories in the repo with `compose.yaml` + `stack.toml` based on the survey
- [ ] Migrate state (if any) using the same approach as Kuma: `sqlite3 .backup` or `tar` of volume contents via Railway CLI
- [ ] Deploy local stacks via Komodo
- [ ] Add ingress rules to `cloudflare-tunnel/compose.yaml` for both
- [ ] Update `dns/dnsconfig.js`: remove Railway CNAMEs, let the tunnel handle both
- [ ] `dns-push`, verify both endpoints resolve to the new local instances
- [ ] Add Kuma monitors for both
- [ ] Decommission Railway projects (keep 72h for rollback, then delete)

### 12. Retire alligator

- [ ] Confirm nothing on `*.pod.haus` routes there
- [ ] Stop alligator's Komodo Core cleanly
- [ ] Power down alligator
- [ ] Open follow-up for syncthing-to-NAS relocation (separate work)

### 13. Rewrite README (last step, after everything is done)

Write the README from as-built reality, not from intent. Deferred to the end so it reflects what we actually built. The current README is stale — it still describes the pre-Komodo `run` script architecture (nginx, certbot, unifi, etc.) with only a small NAS storage section added during this migration.

- [ ] Audit what's actually running on bilby and what lives in the repo
- [ ] Rewrite top-level service list to match reality (remove obsolete sections: Stable but outdated, Stale, Abandoned, External nginx-proxied)
- [ ] Remove the entire Komodo "migration in progress" framing — the migration is done
- [ ] Document the current bootstrap story (`komodo-start`, 1Password → komodo-op → Variables, stack conventions)
- [ ] Preserve the NAS storage section as-is (already current)
- [ ] Add a storage/backup/recovery overview pointing at the restic + rclone flow
- [ ] Add a runbook pointer: "in a disaster, here's how you recover" — one paragraph

## Open questions

(None — all blocking decisions resolved. Execution-level details get decided as we write each phase.)

## Credentials the user will provide

Collected up-front so the execution phases don't stall. Each lives in the 1Password Homelab vault so komodo-op surfaces it as a Komodo Variable.

| Item | 1Password location | Status | Purpose |
|---|---|---|---|
| `railway-api-token` | Homelab vault, `railway-api-token` item, `credential` field | ✓ **ready** | Scripted access to Railway projects (Kuma, doggos, yiayia) |
| `postmark-smtp` | Homelab vault, `postmark-smtp` item. Fields: `username` (API key), `credential` (API key, same value as username), `server`, `port` | ✓ **ready** | Backup + Komodo alert notifications via SMTP |
| `restic-repo-password` | Homelab vault, `restic-repo-password` item, `credential` field (Password type) | ✓ **ready** (48-char base64, ~288 bits entropy, generated and staged into 1P). Annotate the 1Password Emergency Kit hardcopy with a note pointing to this item as part of the migration wrap-up. | Restic repository encryption password |
| `rclone-onedrive-token` | Homelab vault, `rclone-onedrive-token` item (Secure Note), body accessible via `notesPlain` | ✓ **ready** (stored as a Secure Note — multi-line body holds the full `[onedrive]` config block including `token`, `drive_id`, `drive_type`; reference as `op://Homelab/rclone-onedrive-token/notesPlain`) | rclone OneDrive backend for off-site restic repo sync |

All four are accessed at execution time by surfacing them as Komodo Variables via `komodo-op` (matching the existing pattern used by every other secret in this deployment).

### rclone provisioning runbook

One-time browser OAuth dance, done on a laptop (not bilby — needs a GUI browser). Captures the full config section rather than just the token blob so drive_id, drive_type, and region come along for the ride.

**On the laptop:**

1. Install rclone if not already present (`brew install rclone` on macOS)
2. Run `rclone config`
3. Create new remote:
   - `n` → new remote
   - `name>` → `onedrive`
   - `Storage>` → `onedrive` (look for "Microsoft OneDrive" in the numbered list)
   - `client_id>` → blank (press enter)
   - `client_secret>` → blank
   - `region>` → `1` (Microsoft Cloud Global)
   - `Edit advanced config?` → `n`
   - `Use web browser to automatically authenticate?` → `y`
4. Browser opens — sign in to Microsoft account, grant rclone access
5. Back in terminal: pick **OneDrive Personal** from the drive list (usually option 1)
6. Confirm (`y`), quit (`q`)

**Then extract the config section:**

```
rclone config show onedrive
```

Copy the entire output block including the `[onedrive]` header. It looks like:

```
[onedrive]
type = onedrive
token = {"access_token":"...","token_type":"Bearer","refresh_token":"...","expiry":"..."}
drive_id = XXXXXXXXXXXXXXXX
drive_type = personal
```

**Stash in 1Password:**

- Vault: Homelab
- Item name: `rclone-onedrive-token`
- Item type: **Secure Note** (better fit than a Password field — the body is designed for multi-line arbitrary text, so the JSON token can't get mangled)
- Value: paste the full section, `[onedrive]` header included, into the note body
- Referenced at execution time as `op://Homelab/rclone-onedrive-token/notesPlain` (`notesPlain` is the 1Password CLI's name for the Secure Note body field)

## Deferred (non-blocking follow-ups)

- **Plex metadata regeneration validation** — future experiment. If plex cache/metadata turns out to be reliably regenerateable on our setup, we add restic exclusion rules and reclaim ~100 GB of repo space. Not a migration blocker.
- **Syncthing relocation to NAS host** — separate work after alligator is retired.
- **Plex `Preferences.xml` templating (post-Komodo)** — check `plex/Preferences.xml` into the repo as the source of truth, with `PlexOnlineToken` as an `op://Homelab/plex-online-token/credential` reference. Add a `plex-init` container to `plex/compose.yaml` that (a) runs `envsubst` over the template to inject the token from an env var populated by Komodo Variables, (b) verifies live-file identity against the template, restoring from template if the live file is missing or wrong, and (c) enforces a narrow allow-list of critical attrs on every boot (`MachineIdentifier`, `ProcessedMachineIdentifier`, `CertificateUUID`, `AnonymousMachineIdentifier`, `PublishServerOnPlexOnlineKey=1`, `ManualPortMappingMode=1`, `ManualPortMappingPort=32400`, `AcceptedEULA`, `IPNetworkType`, `TranscoderTempDirectory`, `DlnaEnabled`, `LanguageInCloud`). Runtime-mutated attrs (`MetricsEpoch`, `PubSubServerPing`, `LastAutomaticMappedPort`, etc.) are not touched. **Prerequisite:** Komodo running (phase 2) so the secret pipeline is the same `komodo-op` → Komodo Variables → `${VAR}` flow every other stack uses. **Rationale:** Plex identity is a magic string that's catastrophic to lose on a rebuild — having the template in git turns a multi-hour recovery into `git clone` + deploy. Context: this came out of an April 2026 Plex remote-access debugging session that traced the outage to `PublishServerOnPlexOnlineKey="0"` (master "Enable Remote Access" toggle silently off), fixed in the live `Preferences.xml` by setting three attrs — those attrs are only persisted in the container volume right now, which is exactly the fragility we want to eliminate. Full design discussion in the corresponding conversation; key design decisions (narrow allow-list vs blanket overwrite, identity UUIDs committed as plain XML, filename `plex/Preferences.xml`) defaulted and locked.

## Progress log

Updates land here as decisions get made or steps complete.

- Initial survey and planning complete. Document created.
- Confirmed all-on-NFS storage architecture with async mounts. Databases intentionally on NFS under the single-client, low-load, good-backups assumption.
- Backup approach locked in: restic → Pouch repo → rclone sync to OneDrive. Restore testing is a hard gate before any DB stack migrates.
- Plex metadata stays in the backup until regeneration is validated.
- Layered failure coverage confirmed: Jump (SSD) → Pouch (HDD, same NAS, different drives + arrays) → OneDrive (off-site).
- Phase 3 added for backup infrastructure (ahead of stack migrations); phase numbers renumbered.
- Captured NAS characteristics: Jump and Pouch have equal throughput (CPU-bound on NFS controller) but Jump has dramatically better IOPS (~0.1 ms latency). Latency-sensitive workloads → Jump, bulk workloads → Pouch. Our current layout already honours this.
- Added a NAS Storage section to `README.md` reflecting the Jump/Pouch distinction. Full README rewrite added as phase 10 — deferred to the end so it captures as-built reality rather than intent.
- Paperless archive path locked in: `/mnt/pouch/Paperless/` (bind mount into container).
- Logging solution locked in: Loki + Grafana Alloy + Grafana as a Komodo stack, Loki storage on Jump, Grafana at `logs.pod.haus`.
- Autoheal inclusion list decided (see Key decisions).
- Plex metadata confirmed in backups (no exclusions).
- Backup repo layout and encryption approach raised; decisions pending.
- Backup repo layout locked in: single restic repo at `/mnt/pouch/backups/podhaus/restic/` with per-container tags.
- Backup repo path revised to `/mnt/pouch/backups/` (no nesting) after confirming the directory is only used by plex-backup's stale `plex/` subdir, which is being retired as part of rolling plex-backup functionality into the unified restic pre-hook.
- Backup toolchain locked in: Backrest wraps restic for orchestration/UI/hooks/notifications. pgBackRest considered and rejected — PITR value not worth the second-system cost at single-client low-load scale.
- Retire `plex-backup` container; its SQLite integrity + auto-restore behavior rolls into the restic pre-hook wrapper and gets extended to HA and onenote catalog as well.
- Validate-and-maybe-restore pattern defined: SQLite gets dump + integrity_check + auto-restore from last good on retry-exhausted failure. Postgres gets dump + parseability check + alert-only (no auto-restore — too destructive to automate at this scale).
- Backup encryption locked in: restic repo encrypted, password in 1Password Homelab vault via komodo-op, 1P Emergency Kit hardcopy gets annotation noting password location.
- Notification destination locked in: Postmark SMTP, three sources (Backrest via Shoutrrr, Komodo Alerter via Apprise relay, Uptime Kuma native).
- Uptime Kuma added to migration: currently on Railway, migrating to a local Komodo stack via full-state SQLite volume copy (Option A). Phase inserted earlier in the sequence so Kuma watches the stack migrations in flight.
- Two additional Railway services (`doggos`, `yiayia`) added as a new phase 11 after the Cloudflare cutover. Services unknown — will survey when we get there. Railway API token covers all three Railway migrations.
- Phase list reordered: pre-flight → bootstrap → backups → logging → Kuma → arm64 → stack migrations → tunnel cutover → OneNote → paperless upload → Railway extras → retire alligator → README rewrite.
- Credentials preflight table added. Railway token confirmed present in 1Password Homelab vault (`railway-api-token`, credential field). Postmark SMTP, rclone OneDrive token, and restic repo password still to be provisioned.
- Postmark SMTP credentials confirmed present in 1Password Homelab vault (`postmark-smtp` item, fields: `username`, `credential`, `server`, `port`). Rclone OneDrive token and restic repo password still to be provisioned.
- Secret access pattern at execution time: Option 2 confirmed — all credentials surface as Komodo Variables via komodo-op, matching the existing secrets flow.
- Restic repo password generated (48-char base64, ~288 bits entropy), staged into 1Password Homelab as `restic-repo-password` / `credential` field. Tmp file on bilby cleaned up. Emergency Kit annotation still to do as part of migration wrap-up.
- Rclone OneDrive provisioning documented in a runbook section above; user to execute on laptop when they return to the migration. Did not achieve in this session.
- All architectural decisions resolved. Phase 1 (pre-flight cleanup) is credential-free and ready to execute on user's go-ahead. Phases 2–4 need the rclone + restic password credentials in 1Password first.
- Plex remote-access outage debugged and fixed (out-of-band from the migration proper). Root cause: `PublishServerOnPlexOnlineKey="0"` — Plex's master "Enable Remote Access" toggle was silently off, so every publish path was degenerate. Set the toggle + `ManualPortMappingMode=1` + `ManualPortMappingPort=32400` via Plex's `/:/prefs` API; verified external reachability and plex.tv direct + relay connections; user confirmed working over 5G. `plex/README.md` lessons-learned section rewritten. The fix currently lives only in the container-volume `Preferences.xml` on the NAS, which is exactly the fragility the config-as-code principle is meant to eliminate — follow-up added to the deferred list: templating `Preferences.xml` into the repo, to be done after Komodo bootstrap.
- Config-as-code adopted as a first principle for the repo, documented in root `README.md` and captured in memory. Summary: any config that *can* live in the repo, *should*; secrets live in 1Password and are templated in at deploy time; container-volume-only state is not a substitute because the operational reality is those files eventually get lost. This is the guiding reason for the deferred Plex templating follow-up.
- Rclone OneDrive OAuth dance completed. User picked OneDrive Personal (drive_id `397B8A27385EB8E3`) from the drive list. Config stashed in 1Password Homelab as `rclone-onedrive-token`, stored as a **Secure Note** rather than a Password field — the multi-line body is a better fit for the `[onedrive]` config block, and the field reference is `op://Homelab/rclone-onedrive-token/notesPlain`. Phase 3 wiring will need to verify komodo-op picks up Secure Notes (vs Password items) when we get there; if it doesn't, we either fall back to a Password field with manual escaping or sidecar the rclone config rendering outside the komodo-op path. All four migration credentials now ✓ ready — phase 1 is fully unblocked.
