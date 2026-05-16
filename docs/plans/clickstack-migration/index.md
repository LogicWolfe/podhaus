# ClickStack migration

Replace **VictoriaLogs** with **ClickStack** (ClickHouse + the HyperDX
UI + a bundled OpenTelemetry collector + MongoDB) as podhaus's
observability backend. Keep the rest of the logging pipeline — Alloy on
both hosts stays, only its sink changes. Fold **Gatus metrics** into the
same store. **Retire Grafana** entirely; HyperDX becomes the single pane
for logs, traces and metrics, and absorbs the uptime view.

This plan is research + decision matrix + per-stream implementation
plan. No timelines, no estimates — investigation and planning only.
Nothing has been changed in the repo (this plan aside), on either host,
or in Cloudflare.

## Why ClickStack, and what actually changes

VictoriaLogs is a single-binary log store that happens to speak the Loki
push protocol; Alloy ships to it with `loki.write`. ClickStack is a
four-container system and **does not speak Loki** — its bundled OTel
collector ingests **OTLP** (and Fluentd), authenticated by an ingestion
API key. So the migration is not "swap a URL." The real surface area:

| Concern | VictoriaLogs today | ClickStack target |
|---|---|---|
| Store | `victoriametrics/victoria-logs` single binary | `clickhouse-server` + `mongo` (app state) |
| UI | vmui at `logs.pod.haus`; Grafana for dashboards | HyperDX `app` at **`watch.pod.haus`** (new hostname); `logs.*` + Grafana removed |
| Ingest protocol | Loki push (`/insert/loki/api/v1/push`) | OTLP/HTTP `:4318` via bundled OTel collector, **ingestion-key authed** |
| Alloy sink | `loki.write` | `otelcol.receiver.loki` bridge → `otelcol.exporter.otlphttp` |
| Retention | `-retentionPeriod=180d` + `50GB` cap, one flag | ClickHouse table **TTL** (upstream default **3 days** — must be changed) + disk cap strategy |
| Data on disk | `/mnt/jump/victoria-logs`, runs `user: "1000:100"` to survive NFS squash | ClickHouse + Mongo **chown their data dirs at startup** — NFS all-squash on Jump blocks this (see [Stack & storage](clickstack-stack.md)) |
| Metrics | none collected | Gatus `/metrics` scraped → OTLP → ClickHouse |
| Backup | directory is restic-copied by Backrest | ClickHouse can't be file-copied live; **MongoDB app-state backup is the hard part** (see [Backup & DR](backup-and-dr.md)) |
| Resource footprint | tens–hundreds of MB | ClickHouse is memory-hungry on a 15 GB M1 sharing every other stack |

## Status

Nothing migrated. Live snapshot of the relevant podhaus state as of
2026-05-16:

| Component | Current state | Target state |
|---|---|---|
| Log store | `victoria-logs` on bilby, `:9428`, `/mnt/jump/victoria-logs`, 180d/50GB | `clickstack` stack on bilby (ClickHouse, OTel collector, HyperDX, Mongo) |
| Alloy (bilby) | `loki.source.docker` → `loki.process` → `loki.write` → VL `:9428` | same discovery+process; sink → `otelcol.exporter.otlphttp` to local collector `:4318` |
| Alloy (kangaroo) | writes cross-LAN to `10.0.0.119:9428` | writes cross-LAN to bilby collector `10.0.0.119:4318` (OTLP) |
| Log shaping | `stage.decolorize`, per-container JSON rewrite (`op-connect-api`, `flood`), `rtorrent-cleanup` file tail | unchanged — kept verbatim, only the terminal `forward_to` retargets |
| UI | vmui (`logs.pod.haus`) + Grafana (`grafana.pod.haus`) | HyperDX at `watch.pod.haus`; `logs.*` (VL vmui) + `grafana.*` ingress + Access + Grafana stack removed at decommission |
| Gatus | endpoint+heartbeat monitor, **no `/metrics`** exposed | `metrics: true`; Alloy scrapes `gatus:8080/metrics` → OTLP → ClickHouse |
| Uptime dashboard | Grafana Infinity datasource → Gatus API | recreated as a HyperDX dashboard (or Gatus's own status page) |
| Backup | `/mnt/jump/victoria-logs` + `logging_grafana-data` in Backrest plans | new Mongo dump plan; ClickHouse data ephemeral (see decision 1) |
| Cloudflare | `logs.pod.haus`→VL `:9428`, `grafana.pod.haus`→Grafana `:3000` | **new** `watch.pod.haus`→HyperDX (added in Phase C); `logs.*`+`grafana.*` ingress + Access removed at decommission |
| Secrets | none new | HyperDX session secret, ingestion API key, ClickHouse password → 1Password |

## Plan structure

Independent streams — each can be planned or executed on its own, in
roughly this dependency order.

1. [**ClickStack stack**](clickstack-stack.md) — the new single-host
   bilby stack: compose, arm64 image pre-flight, dockernet rework,
   the **NFS-squash vs ClickHouse/Mongo chown** problem, storage tier
   placement, resource limits on the M1, secrets, and the
   **ingestion-key bootstrap chicken-and-egg**.
2. [**Ingestion pipeline**](ingestion-pipeline.md) — reconfigure Alloy
   on both hosts: keep all `loki.process` shaping, replace the
   `loki.write` sink with the Loki→OTLP bridge + authed OTLP exporter.
   Kangaroo's cross-LAN path.
3. [**Retention & storage**](retention-and-storage.md) — the upstream
   3-day TTL trap, reproducing VL's 180d/50GB behaviour with ClickHouse
   TTL + disk-usage caps + column TTL, and sizing on the chosen tier.
4. [**Gatus metrics**](gatus-metrics.md) — enable Gatus `/metrics`,
   scrape via Alloy → OTLP → ClickHouse, rebuild the uptime view in
   HyperDX, and the consequences of retiring Grafana.
5. [**Backup & DR**](backup-and-dr.md) — the MongoDB app-state backup
   (the genuinely complicated part: `mongodump`, ordering, what's lost
   without it), the ClickHouse-data durability decision, and the DR
   rebuild runbook.
6. [**Cutover**](cutover.md) — the hard-swap sequence, the
   stopped-but-intact VL rollback, Cloudflare/Access changes, Grafana
   retirement, VictoriaLogs decommission + Jump reclamation, and the
   docs that must change.

## Open decisions (need user input before any migration step)

Resolved already (captured here so implementers don't re-litigate):

- **Grafana → retired entirely.** HyperDX is the single pane. The
  provisioned uptime dashboard is recreated in HyperDX (or we fall back
  to Gatus's own status page — see [Gatus metrics](gatus-metrics.md)).
- **Cutover → hard swap.** No Alloy dual-ship. VL is left
  *stopped-but-intact* (container down, `/mnt/jump/victoria-logs`
  untouched) as the rollback until ClickStack is trusted, then
  decommissioned. See [Cutover](cutover.md).

Still open:

1. **ClickHouse telemetry durability.** MongoDB app-state backup is in
   scope regardless. For the log/trace/metric data in ClickHouse:
   (a) **ephemeral — don't back it up** (recommended; telemetry is
   regenerable, the pipeline self-heals, and this matches the
   "hard swap / lean" posture — on DR we lose history only);
   (b) native ClickHouse `BACKUP … TO S3` into the existing MinIO
   bucket, which Backrest already mirrors off-site (clean chain, more
   machinery); (c) a `clickhouse-backup` sidecar (most capable,
   most new surface). **Default: (a).** Detail in
   [Backup & DR](backup-and-dr.md).
2. **ClickHouse + Mongo data placement.** Both images `chown` their
   data directory on startup; Jump is NFS `all_squash` to `1000:100`,
   which blocks `chown` (the same wall the Komodo Postgres carve-out
   hit). Options: (a) **local NVMe** `/var/lib/clickstack/...` —
   works; log data is >5 GB so it nominally exceeds the storage-tier
   rule of thumb, but measured volume is only ~9 GB at 180 d — TTL-
   bounded, well within NVMe, matches how Plex/Paperless live on local
   NVMe (recommended);
   (b) Jump with a uid/squash workaround (pre-created dirs +
   `user:` override + skip-chown env) — fragile, image-version
   dependent. **Default: (a).** Detail in
   [Stack & storage](clickstack-stack.md) and
   [Retention & storage](retention-and-storage.md).
3. **Retention target — RESOLVED: 180 d (VL parity).** Settled by
   measuring the live VL instance (2026-05-16): 419 MB for ~30 d real
   data, ~18 MB/day → ~0.5 GB/mo in VL → ~1.5–3 GB/mo in ClickHouse →
   **~9 GB at 180 d** (~15 GB worst-case). Disk is not the constraint
   the plan originally assumed; 180 d keeps parity for single-digit GB
   and removes a decision. The earlier "90 d, hard disk cap"
   recommendation was wrong on the facts and is superseded. Full
   working in [Retention & storage](retention-and-storage.md).
4. **Image version posture.** ClickStack ships HyperDX/collector on a
   rolling major tag (`IMAGE_VERSION=2`) and pins ClickHouse
   (`26.1-alpine`) and Mongo (`5.0.32-focal`). Per the
   "don't pin fast-moving clients" guidance, track the rolling tag for
   HyperDX/collector and pin the stateful pair (ClickHouse, Mongo) to
   the upstream-tested versions, recording the version in a comment.
   Confirm.
5. **HyperDX auth model — RESOLVED: single `nathan` admin account.**
   Research (2026-05-16) confirmed HyperDX **OSS has no SSO, OIDC,
   SAML, trusted-header/proxy, anonymous, or declarative-credential
   auth** — only local username/password via the first-run wizard
   ([OSS-vs-Cloud](https://www.hyperdx.io/docs/oss-vs-cloud);
   open feature request [hyperdx#1329](https://github.com/hyperdxio/hyperdx/issues/1329),
   no implementation). So Cloudflare Access cannot pass an auth header
   HyperDX will honour. Decision: one personal **`nathan`** admin
   account (not a "shared" account), credentials in 1Password,
   Cloudflare Access (Family identity) remains the real gate — parity
   with how Grafana sat behind Access. Additional people get their own
   accounts only if ever needed. Revisit if #1329 ships upstream.

## Credentials that will need 1Password Homelab vault entries

Each becomes a Komodo Variable via `komodo-op`
(`OP__KOMODO__<ITEM>__<FIELD>`). See [Secrets](/secrets.html).

- `ClickStack session secret` — `EXPRESS_SESSION_SECRET`,
  `openssl rand -hex 32`. HyperDX cookie/session signing.
- `ClickStack ingestion key` — the OTLP ingestion API key. **Generated
  by HyperDX on first boot**, not chosen by us — captured into 1Password
  *after* bootstrap, then fed to Alloy (bootstrap ordering wrinkle, see
  [Stack & storage](clickstack-stack.md) and
  [Cutover](cutover.md)).
- `ClickStack ClickHouse password` — strong password for the ClickHouse
  `default` user (upstream compose ships it blank).
- `ClickStack Mongo` — only if we enable Mongo auth (it's on the
  internal-only path by default; see [Backup & DR](backup-and-dr.md)).

## Hard rules (reminders for the implementers)

From [AGENTS.md](/AGENTS.md) and the runbooks — every one is relevant
here:

- **Never single-file bind mounts.** Bind the containing directory.
  ClickHouse `config.xml`/`users.xml` overrides go in a bound *config
  directory*, not file binds.
- **Always absolute host paths** — `${PODHAUS_REPO}/clickstack/...`,
  never relative.
- **Never create Komodo Variables in the UI** — 1Password is the source
  of truth, even for the HyperDX-generated ingestion key.
- **No fallbacks that mask failure.** If Alloy can't reach the
  collector, it must fail loudly — do not add a "fallback to VL" branch.
  Hard swap means hard swap.
- **Don't push, deploy, `komodo-sync`, or `tf apply` without explicit
  authorization.** `tf plan` is fine. `git push` now triggers the
  GitHub webhook → Komodo auto-deploy.
- **dockernet by container name, never static IP.** ClickStack's
  upstream `internal` network is replaced with `dockernet`.

## Cross-references

- [Architecture](/architecture.html)
- [Stack conventions](/stack-conventions.html)
- [Komodo](/komodo.html)
- [Secrets](/secrets.html)
- [Storage](/storage.html)
- [Backup & recovery](/backup-and-recovery.html)
- [Monitoring](/monitoring.html)
- [Networking](/networking.html)
- [Hosts](/hosts.html)
- Upstream: [ClickStack architecture](https://clickhouse.com/docs/use-cases/observability/clickstack/architecture),
  [Docker Compose deployment](https://clickhouse.com/docs/use-cases/observability/clickstack/deployment/docker-compose),
  [Managing TTL](https://clickhouse.com/docs/use-cases/observability/clickstack/ttl),
  [ClickStack repo `docker-compose.yml`](https://github.com/ClickHouse/ClickStack/blob/main/docker-compose.yml)
