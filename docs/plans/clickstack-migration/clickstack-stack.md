# ClickStack stack

The new single-host bilby stack. ClickStack is bilby-only, exactly as
VictoriaLogs was — kangaroo only runs Alloy and ships cross-LAN. This is
a normal single-host podhaus stack: `clickstack/compose.yaml` +
`clickstack/stack.toml`, `files_on_host = true`,
`run_directory = "/etc/komodo/repo/clickstack"`, joined to `dockernet`.

## Upstream shape (what we're adapting)

The upstream [`docker-compose.yml`](https://github.com/ClickHouse/ClickStack/blob/main/docker-compose.yml)
has four services on a private `internal` network:

- **`db`** — `mongo:5.0.32-focal`, volume `.volumes/db:/data/db`.
  Stores HyperDX *application state*: users, dashboards, alerts, saved
  searches, source/connection definitions. **Not** telemetry.
- **`ch-server`** — `clickhouse/clickhouse-server:26.1-alpine`,
  `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1`, binds
  `config.xml`/`users.xml` and volumes `.volumes/ch_data:/var/lib/clickhouse`,
  `.volumes/ch_logs:/var/log/clickhouse-server`. The telemetry store.
- **`otel-collector`** — ClickStack's *opinionated* collector image
  (`${CH_IMAGE_REPO}/${NEXT_OTEL_COLLECTOR_IMAGE_NAME_DOCKERHUB}:${IMAGE_VERSION}`).
  Ports: `4317` (OTLP gRPC), `4318` (OTLP HTTP), `24225` (Fluentd),
  `13133` (health), `8888` (its own Prometheus self-metrics).
  `CLICKHOUSE_ENDPOINT=tcp://ch-server:9000`, `OPAMP_SERVER_URL=http://app:4320`.
  It auto-creates the `otel_logs` / `otel_traces` / `otel_metrics_*`
  tables on first ingest and is remotely configured by HyperDX via
  OpAMP.
- **`app`** — HyperDX (`${HDX_IMAGE_REPO}/${IMAGE_NAME_DOCKERHUB}:${IMAGE_VERSION}`).
  Ports: `HYPERDX_APP_PORT=8080` (UI), `HYPERDX_API_PORT=8000`,
  `HYPERDX_OPAMP_PORT=4320`. `MONGO_URI=mongodb://db:27017/hyperdx`,
  `DEFAULT_CONNECTIONS` points at `http://ch-server:8123` user
  `default` (blank password upstream), `DEFAULT_SOURCES` wires the
  logs/traces/metrics/sessions sources.

Versions come from upstream's `.env` (`CODE_VERSION=2.8.0`,
`IMAGE_VERSION=2`, `HYPERDX_APP_PORT=8080`, `HYPERDX_API_PORT=8000`,
`HYPERDX_OPAMP_PORT=4320`, `USAGE_STATS_ENABLED`,
`HYPERDX_OTEL_EXPORTER_CLICKHOUSE_DATABASE=default`).

## Adaptations for podhaus

### Network: `internal` → `dockernet`

Drop the upstream `internal` network. All four services join
`dockernet` (top-level `networks: { dockernet: { external: true } }`,
each service `networks: [dockernet]`). Inter-service references stay by
container name (`ch-server`, `db`, `app`, `otel-collector`) — Docker
DNS, never static IP. Container names must be globally unique on the
host: rename `db` → `clickstack-mongo`, `ch-server` →
`clickstack-clickhouse`, `otel-collector` → `clickstack-otel`,
`app` → `hyperdx` (and update every cross-reference URI accordingly).

### Ports: publish only what's needed

VictoriaLogs published `9428` to the LAN+dockernet. ClickStack's
attack surface is larger. Publish to the host **only**:

- `4318` (OTLP/HTTP) — kangaroo's Alloy ships here cross-LAN to
  `10.0.0.119:4318`. Bilby's Alloy reaches it in-network as
  `clickstack-otel:4318` and needs no host publish.
- The HyperDX UI port reaches the Cloudflare tunnel via dockernet by
  container name (`http://hyperdx:8080`) — **no host publish**, same as
  every other tunnel-fronted service.

Do **not** publish `8123`/`9000` (ClickHouse), `27017` (Mongo),
`4317`, `24225`, `8888`, `8000`, `4320`. They're dockernet-internal.
Upstream already comments these out "for security" — keep them off.

### arm64 pre-flight (blocking check)

bilby is Apple M1 (`aarch64`, Fedora Asahi). Before anything else,
confirm every image has an arm64 manifest:

- `clickhouse/clickhouse-server:26.1-alpine` — multi-arch, arm64 ✓.
- `mongo:5.0.32-focal` — arm64 manifest exists. MongoDB ≥ 5.0 needs
  ARMv8.2-A + crypto; Apple M1 is ARMv8.4+ ✓. (This is *not* the
  x86 AVX caveat — irrelevant on arm64.)
- HyperDX `app` and the ClickStack `otel-collector` custom image —
  **verify the arm64 manifest explicitly** with
  `docker manifest inspect` for the chosen `IMAGE_VERSION`. ClickStack
  publishes arm64 but the bundled-collector image has historically
  lagged amd64 on point releases. If arm64 is missing for the pinned
  tag, that gates the version choice (decision 4 in the
  [index](index.md)) — do not paper over it with `platform: linux/amd64`
  emulation; that is a fail-fast violation and qemu'd ClickHouse on a
  15 GB box is a non-starter.

### SELinux (bilby)

Fedora Asahi is enforcing. Config-dir binds and the docker-socket-less
services still need either `:z` on the volume or
`security_opt: [label:disable]`, matching every other bilby stack.
HyperDX does not need the docker socket. None of the four services need
privileged access.

## The NFS-squash vs chown wall (decision 2)

VictoriaLogs lives on Jump (`/mnt/jump/victoria-logs`) and only works
there because it runs `user: "1000:100"` and never `chown`s its data
dir — Jump is NFS exported `all_squash` to `1000:100`, so any
`chown` inside a container fails.

**ClickHouse and Mongo both `chown` their data directory on startup.**
`clickhouse-server` recursively chowns `/var/lib/clickhouse` to uid
`101`; `mongo` chowns `/data/db` to `999`. On NFS all-squash both
fail and the container crash-loops. This is exactly the wall the Komodo
Postgres/FerretDB carve-out hit.

**Recommended (decision 2a): local NVMe.**

```
/var/lib/clickstack/clickhouse   → /var/lib/clickhouse
/var/lib/clickstack/clickhouse-logs → /var/log/clickhouse-server
/var/lib/clickstack/mongo        → /data/db
```

This breaks the storage-tier rule of thumb (log data exceeds the
"< 5 GB → local" guideline) so it **must** be hard-capped — see
[Retention & storage](retention-and-storage.md). It is, however, the
same posture Plex and Paperless already use (large, hot, must-survive-
restart state on local NVMe), and it sidesteps the squash problem
entirely. Local NVMe on bilby is far larger than the 15 GB RAM; the
constraint is the disk cap we choose, not capacity.

The Jump-with-workaround alternative (2b) means pre-creating the data
dirs at the squash uid, overriding `user:` on both containers, and
relying on undocumented skip-chown behaviour that differs across
ClickHouse/Mongo image versions. It's fragile and version-coupled —
documented only as the fallback if local NVMe capacity ever becomes the
binding constraint.

## ClickHouse on a 15 GB M1 (resource constraint)

This is the single biggest operational risk and the sharpest departure
from VictoriaLogs. VL idled at tens–hundreds of MB. ClickHouse is
memory-hungry by design (mark cache, uncompressed cache, query memory,
background merges) and shares bilby with Komodo Core, Plex, Paperless,
Home Assistant, 1Password Connect, Backrest, Gatus, Alloy and the
tunnel.

Mitigations to bake into the bound `config.xml`/`users.xml` override
(directory bind, not file binds — Hard Rules):

- `max_server_memory_usage_to_ram_ratio` low (e.g. `0.3`) or an
  absolute `max_server_memory_usage` cap.
- Shrink `mark_cache_size`, `uncompressed_cache_size`.
- Per-query `max_memory_usage` + `max_bytes_before_external_group_by`
  in the profile so a bad HyperDX query degrades instead of OOM-killing
  ClickHouse.
- Compose `mem_limit` / `cpus` on `clickstack-clickhouse` as a hard
  ceiling, sized against `free -m` on bilby at steady state.
- `clickhouse-alpine` is the lighter image — keep it.

Validate under real ingest before cutover, not after. If bilby can't
comfortably host ClickHouse alongside everything else, that is a
finding to surface, not engineer around — flag it before
[cutover](cutover.md).

## Secrets & the ingestion-key chicken-and-egg

Per [Secrets](/secrets.html): items go in the 1Password Homelab vault,
`komodo-op` syncs them to `OP__KOMODO__*` Komodo Variables, referenced
as `[[VAR]]` in `stack.toml`'s `environment` block. Never hand-create
the variable in the Komodo UI.

- `EXPRESS_SESSION_SECRET` — `openssl rand -hex 32`, into 1Password
  *before* first deploy.
- ClickHouse `default` password — set in the bound `users.xml`, and the
  same value in HyperDX's `DEFAULT_CONNECTIONS` (override the upstream
  blank password). Into 1Password before first deploy.
- `USAGE_STATS_ENABLED=false` — opt out of upstream telemetry
  (homelab privacy posture; not a secret but a deliberate default).

**The ingestion key cannot be pre-provisioned.** HyperDX generates the
OTLP ingestion API key on first boot and surfaces it in
*Team Settings → API Keys*. Alloy needs it to authenticate to the
collector. So bootstrap is inherently two-phase:

1. Deploy ClickStack. Complete the HyperDX first-run (create the
   `nathan` admin account, decision 5).
2. Copy the generated ingestion key into the 1Password
   `ClickStack ingestion key` item; `komodo-op` syncs it.
3. *Then* deploy the Alloy reconfig referencing
   `[[OP__KOMODO__CLICKSTACK_INGESTION_KEY__CREDENTIAL]]`
   (see [Ingestion pipeline](ingestion-pipeline.md)).

This ordering is the spine of the [cutover](cutover.md) sequence. Until
step 3, ClickStack is up but receiving nothing — which is fine, because
the hard swap hasn't happened yet and VL is still serving.

## Komodo registration

- `clickstack/stack.toml`: `server = "podhaus"`,
  `files_on_host = true`, `run_directory = "/etc/komodo/repo/clickstack"`,
  `tags = ["podhaus"]`, the `environment` block with all `[[VAR]]`
  references, autoheal label + healthchecks on all four services
  (standard 60s/10s/3/30s pattern). HyperDX healthcheck against its
  own `/` ; ClickHouse against `clickhouse-client --query 'SELECT 1'`
  or the `8123/ping` endpoint; Mongo against `mongosh --eval` ;
  collector against `13133`.
- `./komodo-sync` registers it; the smart-deploy pass deploys it (or
  the GitHub-webhook path). **Authorization required** before either.

## Deployment gotchas (as-built, 2026-05-16)

Two non-obvious failures hit during the real deploy — both now fixed in
`clickstack/`, captured here because neither is visible from the compose
file alone and both will recur on any rebuild/DR:

1. **The collector needs ClickHouse credentials, not just ClickHouse.**
   Upstream ClickStack works because its ClickHouse has a *blank*
   password. We set `CLICKHOUSE_PASSWORD` on the server, so the
   OpAMP-delivered ClickHouse exporter fails with *"Agent crashed during
   config application"* until the collector *also* gets
   `CLICKHOUSE_USER=default` + `CLICKHOUSE_PASSWORD` (same secret
   HyperDX gets via `DEFAULT_CONNECTIONS`). If you ever rotate the
   ClickHouse password, rotate it in three places: server env, HyperDX
   `DEFAULT_CONNECTIONS`, collector env.
2. **Bind-mounting `config.d` shadows the image's
   `docker_related_config.xml`.** That image file is what sets
   `listen_host=0.0.0.0`; shadowing it drops ClickHouse back to
   config.xml's loopback-only bind. The in-container healthcheck still
   passes (it hits localhost) so the container reports *healthy* while
   nothing on dockernet can reach 9000/8123 — collector + HyperDX get
   *"connection refused"*. The drop-in must restore
   `<listen_host>0.0.0.0</listen_host>` + `<listen_try>1</listen_try>`.
   Health-is-green-but-unreachable is the trap: prefer an off-box
   reachability probe over the container healthcheck when validating.

Bootstrap itself was **fully headless** — no wizard. `POST
/register/password` (port 8000, `{email,password,confirmPassword}`,
409-guarded) creates the `nathan` account + team; the ingestion key is
the team's `apiKey` (uuidv4) read straight from Mongo
(`db.teams.findOne().apiKey`) and stored to 1P `clickstack-ingestion-key`.

3. **ClickHouse part-explosion → autoheal restart loop (fixed; has a
   follow-up).** Surfaced during Phase D. The bundled OTel collector
   inserts frequently → many small MergeTree parts. ClickHouse attaches
   *all* parts before opening `:8123`, so cold-start time grew with the
   data until it exceeded the healthcheck `start_period` (60s); autoheal
   then killed it before it was ready, every ~3 min, a self-perpetuating
   loop (not a crash — functional between kills; ingest held via the
   collector's retry buffer). Two-part fix: (a) `start_period` 60s→300s,
   `retries` 3→5 so a slow start / heavy query never trips autoheal on
   the whole DB; (b) `<async_load_databases>true</async_load_databases>`
   in the config.d drop-in so ClickHouse opens listeners immediately and
   loads tables in the background — startup is decoupled from part
   count. **Open follow-up:** the underlying part explosion (collector
   insert batching / `async_insert`) should be tuned so merges keep up
   and part count stays bounded; the OpAMP-managed collector config is
   the lever (out of scope for the migration itself). Watch
   `system.parts` count and background-merge backlog during the soak.

## Open questions for this stream

- Exact ClickHouse memory ceiling — needs `free -m` on bilby at steady
  state and a real ingest sample. Carried into
  [Retention & storage](retention-and-storage.md). (Hard cap
  `mem_limit: 4g` is in place as the guard meanwhile.)
- ~~arm64 manifest for the bundled collector~~ — RESOLVED: all four
  images have `linux/arm64` manifests (verified `docker manifest
  inspect`, 2026-05-16).
- ~~`FRONTEND_URL`/`HYPERDX_APP_URL`~~ — RESOLVED: set to
  `https://watch.pod.haus`; confirmed live (HyperDX emits
  `access-control-allow-origin: https://watch.pod.haus`).
