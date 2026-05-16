# Retention & storage

VictoriaLogs encodes retention in two flags:
`-retentionPeriod=180d` and `-retention.maxDiskSpaceUsageBytes=50GB`,
with data at `/mnt/jump/victoria-logs`. ClickStack has neither flag.
Retention is a **ClickHouse table TTL**, the disk cap is a separate
concern, and the upstream default is a trap.

## The 3-day TTL trap

ClickStack's bundled OTel collector creates `otel_logs`, `otel_traces`,
`otel_metrics_*` with a **default TTL of 3 days**. The ClickHouse docs
say plainly that "the default of 3 days often needs to be modified."
If we deploy and walk away, we will have *silently replaced 180-day log
retention with 3-day retention* — a classic fail-quiet that won't
surface until someone needs a two-week-old log and it's gone. Changing
the TTL is a **required cutover step**, not an optional tuning pass.

Two levers (use both):

1. **Collector exporter `ttl`.** The ClickHouse exporter in the bundled
   collector takes a `ttl` parameter that sets the TTL expression on
   the tables it auto-creates (e.g. `ttl: 2160h` for 90 days). Because
   the collector is configured by HyperDX over OpAMP, this is set
   through HyperDX's collector configuration, not a static file —
   confirm where the override lives for the pinned `IMAGE_VERSION`
   (OpAMP-managed config vs a mountable collector config). This governs
   *newly created* tables.
2. **`ALTER TABLE … MODIFY TTL`.** If the tables already exist (e.g.
   the collector created them at 3 d before we set the exporter value),
   the exporter `ttl` does not retroactively change them. Run an
   explicit `ALTER TABLE otel_logs MODIFY TTL TimestampTime + INTERVAL
   <N> DAY` (and the traces/metrics tables) once, post-bootstrap. This
   is idempotent and belongs in the cutover checklist.

## Retention target (decision 3 — resolved by measurement)

**Decision of record: 180 days, VL parity.** This was settled by
measuring the live VictoriaLogs instance on bilby (2026-05-16), not
estimated:

- VL on-disk total: **419 MB**, for **~30 days** of real data (ingest
  only started ~2026-04-16 — the configured 180 d / 50 GB has never
  been approached; nobody actually has 180 days of logs).
- Steady-state: ~13 MB/day late April rising to **~18 MB/day** now →
  **≈ 0.5–0.6 GB/month** in VictoriaLogs.

ClickHouse's `otel_logs` wide-event schema (Body + attribute maps +
materialized columns + token/bloom skip indexes) is reliably **less
compact than VL — roughly 2–5×**. So the ClickHouse equivalent is
**≈ 1.5–3 GB/month**, and the retention math is:

| Retention | VL | ClickHouse ~3× | ClickHouse ~5× |
|---|---|---|---|
| 90 d | ~1.5 GB | ~4.5 GB | ~7.5 GB |
| **180 d** | ~3 GB | **~9 GB** | ~15 GB |

180-day parity costs **under ~10 GB of local NVMe** (≤ ~15 GB
worst-case) — a rounding error next to Plex/Paperless. **Disk is not
the constraint**, which is the opposite of this plan's original
assumption. Going shorter would save single-digit GB and *add* a
decision; 180 d keeps parity with what users expect and removes the
decision.

- `otel_logs` TTL: `TimestampTime + INTERVAL 180 DAY`.
- `otel_traces`: 30 d (no traces today — nothing emits OTLP traces —
  so this is purely a future guard).
- `otel_metrics_*`: 90 d is ample; Gatus metrics are ~15 low-
  cardinality endpoints, negligible volume.

The real ClickHouse constraint is **RAM / merge overhead**
([Stack & storage](clickstack-stack.md)), which is essentially
independent of this tiny retention — not disk.

## Disk cap — there is no `maxDiskSpaceUsageBytes`

VL's 50 GB hard cap has no direct ClickHouse equivalent: TTL bounds
retention *by time*, not *by size*. With the measured volume (~9 GB at
180 d, ~15 GB worst-case) this is **no longer a real risk** — even a
10× traffic anomaly for a sustained week is still well inside the local
NVMe headroom, and the daily TTL merge reclaims it. The elaborate
size-cap machinery the plan originally called for is unwarranted at
this scale. What remains worth doing, in order:

1. **TTL set by time (above), period.** At this volume
   `bytes_per_day × days` is single-digit GB; no size-based cap needed.
2. **A monitored disk-usage alarm** on the ClickHouse data path as a
   cheap backstop — a HyperDX alert on a disk metric, or a Gatus
   heartbeat (see [Gatus metrics](gatus-metrics.md)). Not because we
   expect to hit it, but because VL's cap was self-enforcing and
   ClickHouse's TTL isn't — so an unattended runaway (e.g. a wedged
   container log-spamming) should page rather than silently fill NVMe.
   This is good practice, not a cutover blocker.
3. ClickHouse storage policies / quotas / `TTL … TO VOLUME` — explicit
   non-goal. Filed only as the lever if volume ever grows 50–100× from
   today.

Column-level TTL is also available: drop heavy columns earlier than
rows where they don't earn their retention (upstream specifically
recommends keeping `Body` long in case new dynamic metadata needs
re-extraction). Filed as a later optimisation, not cutover-blocking.

## Storage placement (ties to decision 2)

[Stack & storage](clickstack-stack.md) establishes that ClickHouse and
Mongo `chown` their data dirs and Jump's NFS all-squash blocks that, so
data goes on **local NVMe** (`/var/lib/clickstack/...`). Consequences
specific to retention:

- The disk budget is the **local NVMe free space on bilby**, shared
  with every other `/var/lib/<stack>` consumer (Plex DB, Paperless
  pgdata/data, Home Assistant, flood, MinIO, Komodo state…). At the
  measured ~9 GB-for-180 d this is comfortably absorbed — moving off
  Jump's ~358 GB free onto local NVMe is *not* the tightening this plan
  originally feared, because the real footprint is single-digit GB, not
  the 50 GB the VL cap suggested.
- ClickHouse `ch_logs` (`/var/log/clickhouse-server`) also grows; give
  it its own bounded directory and ClickHouse log rotation in the
  config override, or it quietly co-consumes the budget.
- Freeing `/mnt/jump/victoria-logs` on decommission reclaims only the
  **actual VL footprint (~0.4 GB today)**, not the 50 GB cap — a
  negligible Jump benefit, and irrelevant to the NVMe budget. The plan
  text elsewhere that says "up to ~50 GB" referred to the cap, not real
  usage; corrected here. See [Cutover](cutover.md).

If the local-NVMe budget proves too tight for a useful retention window,
that is a genuine architectural finding (ClickHouse is simply a
heavier store than VL for this box) — surface it for a decision
(shorter retention, the Jump-squash workaround in decision 2b, or
accept ephemerality per decision 1), don't silently truncate retention
to make it fit.

## Validation before declaring done

- `SHOW CREATE TABLE otel_logs` shows the intended TTL expression, not
  3 days.
- A row inserted with an old synthetic timestamp is reaped on the next
  TTL merge (proves TTL is actually active, not just declared).
- `system.tables` on-disk size after a representative ingest period
  extrapolates to within the chosen NVMe budget at the chosen TTL.
- The disk-usage backstop alert fires in a forced test.
