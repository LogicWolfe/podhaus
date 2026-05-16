# Backup & DR

You flagged the Mongo backup as "might be a bit complicated." It is —
not because `mongodump` is hard, but because of *what's in Mongo*,
*ordering*, and the fact that Backrest's model (restic-copy a quiescent
directory) doesn't fit a live database. ClickHouse durability is a
separate, deliberately simpler decision.

## What actually needs backing up

Two stores, very different value/volume profiles:

| Store | Contents | Volume | Regenerable? |
|---|---|---|---|
| **MongoDB** (`clickstack-mongo`) | HyperDX app state: users, **dashboards**, **alerts**, saved searches, **source/connection definitions**, team + ingestion-key config | Tiny (MB) | **No.** Lose this and every dashboard/alert/saved query is gone, and HyperDX first-run must be redone |
| **ClickHouse** (`clickstack-clickhouse`) | `otel_logs` / `otel_traces` / `otel_metrics_*` — the telemetry itself | Large (GB), TTL-bounded | Yes, going forward — the pipeline self-heals on restart; only *history* is lost |

So the priority is inverted from intuition: the **small** store is the
**critical** one. VL conflated these — its single directory held the
(only) data and was restic-copied wholesale. ClickStack splits state
from telemetry, and the backup strategy must split with it.

## MongoDB — the complicated part

### Why Backrest can't just bind-mount it

Backrest backs up *quiescent directories*. `/data/db` is a live
WiredTiger database; restic-copying it hot yields a torn, likely
unrestorable snapshot (checkpoint vs journal skew). Every other podhaus
DB backup sidesteps this: Paperless/Komodo Postgres are captured as
*data directories that happen to restore* for this homelab's blast
radius, and that's been accepted. For HyperDX state we should do it
properly because it's small and irreplaceable — a logical dump.

### Approach: scheduled `mongodump` into a Backrest-covered directory

1. A small scheduled job runs
   `mongodump --uri mongodb://clickstack-mongo:27017/hyperdx
   --archive=/dump/hyperdx-$(date +%F).archive --gzip`
   into a host directory, e.g. `/var/lib/clickstack/mongo-dumps/`,
   keeping the last N.
2. That directory is bind-mounted **read-only into Backrest**
   (`/var/lib/clickstack/mongo-dumps → /userdata/clickstack/mongo:ro`)
   and added as a Backrest plan in `backup/bilby/config.json.tmpl`,
   inheriting the existing restic-repo encryption + the nightly
   OneDrive rclone mirror. The dump is quiescent, so restic copies it
   safely; off-site falls out for free via the existing
   `backrest-state` hook chain.

This reuses the entire existing backup/off-site machinery — the only
new thing is producing a consistent dump file.

### Scheduling — decided

**Decision of record: an ofelia job runs `mongodump` at 03:50.** This
matches the existing ofelia scheduling pattern
([Scheduling](/scheduling.html)) and sits inside the **04:00 AWST
dead-time window**. 03:50 is deliberately *before* the Backrest plans
(which start 04:00), so the freshest dump is already sitting in
`/var/lib/clickstack/mongo-dumps/` when Backrest's `clickstack` plan
fires that same night — no off-by-one-night staleness. Local retention
~14 daily archives; restic's own retention then governs long-term.

Implementation: an ofelia job invoking `mongodump` against
`clickstack-mongo` on dockernet (a tiny `mongo`-image one-shot, or
`docker exec` into the running container).

The two alternatives considered and rejected: a Backrest pre-backup
hook on the `clickstack` plan (tightest dump→snapshot consistency but
couples DB logic into Backrest's hook config); a dedicated sidecar with
its own cron (more moving parts). Neither earns its cost over the
ofelia job for a database this small and low-write. This is settled —
not a cutover-time consult.

### Mongo auth wrinkle

Upstream runs Mongo with **no auth** on the private network. On
dockernet it's reachable by any container by name. For this homelab's
posture that mirrors the existing accepted Postgres/FerretDB exposure
and is probably fine — but it means `mongodump` needs no credentials
*and* so does anything else on dockernet. If we enable Mongo auth
(decision: optional, `ClickStack Mongo` 1Password item), the dump URI,
the HyperDX `MONGO_URI`, and the restore procedure all gain a
credential. Recommendation: leave unauthenticated (LAN/dockernet-only,
matches existing posture, don't overindex on security for personal
scale) unless the user wants it hardened — flag, don't gold-plate.

### Restore

Restore = restic-restore the latest archive, then
`mongorestore --gzip --archive=<file> --drop` into a fresh
`clickstack-mongo`. This brings back dashboards/alerts/sources/users.
**The ingestion key lives in Mongo** — restoring it means Alloy's
existing `[[VAR]]` keeps working *if* the restored key matches the one
in 1Password. If Mongo is lost and rebuilt from scratch (no restore),
HyperDX generates a *new* ingestion key and the 1Password item +
`komodo-op` sync + Alloy redeploy must be redone (the bootstrap
chicken-and-egg from [Stack & storage](clickstack-stack.md), again).
Document this explicitly in the runbook — it's the non-obvious DR
failure mode.

## ClickHouse — durability decision (index decision 1)

ClickHouse **cannot be safely file-copied live** (parts + merges +
inserts in flight) — the same reason Mongo can't, more so. So the VL
approach (Backrest bind-mounts the data dir) is not available. Options,
recommendation first:

1. **Ephemeral — don't back it up (recommended).** Telemetry is
   regenerable; the pipeline resumes on restart; only history is lost.
   This matches the lean / hard-swap posture and the reality that logs
   are operational exhaust, not records of truth. On DR: ClickStack
   comes back empty and refills from `now`. No new machinery.
2. **Native `BACKUP TABLE … TO S3(...)` → existing MinIO.** ClickHouse
   has a first-class consistent `BACKUP` statement. Target the existing
   MinIO bucket; Backrest already backs up `/var/lib/minio` and the
   `backrest-state` hook already mirrors it to OneDrive — so a
   ClickHouse backup into MinIO inherits the *entire* existing
   encrypted off-site chain with zero new off-site plumbing. Cost: a
   scheduled `BACKUP` statement (ofelia, same slot logic as the Mongo
   dump) and MinIO bucket growth feeding the disk budget.
3. **`clickhouse-backup` sidecar.** Incremental, schedule-aware, most
   capable; most new surface and another container on a memory-tight
   box. Only if (2) proves insufficient.

This is **open decision 1** in the [index](index.md); default **(1)**.
Note (2) is genuinely clean here *because MinIO already exists and is
already backed up* — if the user wants log history to survive DR, (2)
is the low-marginal-cost path, not (3).

## DR rebuild runbook (target shape)

To be written as `docs/runbooks/clickstack.html` (or folded into
[disaster-recovery](/disaster-recovery.html)). Skeleton:

1. Deploy `clickstack` stack (Komodo). ClickHouse + collector tables
   auto-create on first ingest; **set the non-default TTL immediately**
   (see [Retention & storage](retention-and-storage.md)) — easy to
   forget on a panicked rebuild and you'd silently get 3-day retention.
2. Restore Mongo from the latest restic archive (`mongorestore --drop`)
   → dashboards/alerts/sources/users/ingestion-key return.
3. If Mongo was *not* restored: complete HyperDX first-run, capture the
   new ingestion key into 1Password, `komodo-op` sync, redeploy the
   `logging` stack so Alloy picks up the new key.
4. ClickHouse telemetry: per decision 1, either accept empty-and-
   refilling (1) or restore from MinIO `RESTORE` (2).
5. Verify ingest end-to-end (Alloy → collector → HyperDX search shows
   live `flood`/`op-connect-api` lines and kangaroo logs).

## Changes to existing backup wiring

- **Add** `clickstack` plan to `backup/bilby/config.json.tmpl`
  (the Mongo dump dir; optionally the MinIO-resident ClickHouse backup
  if decision 1 → 2).
- **Add** the read-only Mongo-dump bind to `backup/bilby/compose.yaml`.
- **Remove** on VL/Grafana decommission (see [Cutover](cutover.md)):
  the `/mnt/jump/victoria-logs` bind, the `logging_grafana-data`
  external volume + bind, and the corresponding entries from the
  `logging` Backrest plan. Net Jump reclamation: ~0.4 GB (actual VL
  footprint today, not the 50 GB cap — negligible, and irrelevant to
  the NVMe budget — see
  [Retention & storage](retention-and-storage.md)).
- The encryption (`RESTIC_REPO_PASSWORD` from 1Password), the kangaroo
  separate-repo topology, and the OneDrive mirror are all **unchanged**
  — we're adding/removing plans, not touching the backup architecture.

## Validation before declaring done

- A `mongodump` archive restores into a throwaway Mongo and HyperDX
  shows the dashboards/alerts (proves the dump is consistent and
  complete, not just non-empty).
- The dump file appears in a restic snapshot and in the OneDrive mirror
  (proves it rode the existing off-site chain).
- Forced DR drill: wipe `clickstack` volumes, run the runbook, confirm
  app-state returns and ingest resumes — including the
  ingestion-key-regenerated path if Mongo isn't restored.
