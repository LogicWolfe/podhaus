# Ingestion pipeline

"The rest of the logging stack can stay" is true with one caveat: Alloy
stays, every `loki.process` shaping stage stays verbatim, but the
**sink** changes from Loki-push to authenticated OTLP. This is the only
edit to `logging/`, and it's the same edit on both hosts.

## Current Alloy pipeline (unchanged except the tail)

`logging/bilby/alloy-conf/config.alloy` today:

```
discovery.docker "containers"        → discover containers via docker.sock
discovery.relabel "container_logs"   → container / stream / compose_* labels
loki.source.docker "containers"      → forward_to loki.process.containers
loki.process "containers"            → stage.decolorize
                                        stage.match {op-connect-api} json→_msg
                                        stage.match {flood} json(msg)→output
                                        forward_to loki.write.local
local.file_match "rtorrent_cleanup"  → /var/log/flood/rtorrent-cleanup.log
loki.source.file  "rtorrent_cleanup" → forward_to loki.write.local
loki.write "local"                   → http://victoria-logs:9428/insert/loki/api/v1/push
```

Everything above `loki.write` is doing useful, hard-won work
(ANSI stripping so JSON parsers and the UI behave; per-container message
extraction for `op-connect-api` and `flood`; the `rtorrent-cleanup`
file tail that can't reach a docker log stream because rtorrent forks
the hook). **None of it changes.** Only the terminal sink does.

## The protocol gap

VictoriaLogs accepts the Loki push protocol natively, which is why the
config comment says Alloy's `loki.*` components were "unchanged from the
previous Loki setup — only the URL differs." ClickStack's bundled OTel
collector does **not** speak Loki. It accepts OTLP (gRPC `4317`,
HTTP `4318`) and Fluentd (`24225`). So we can't just change the URL —
we need to convert Loki-shaped entries to OTLP inside Alloy.

Alloy is itself an OpenTelemetry Collector distribution, so it has the
bridge built in:

- `otelcol.receiver.loki` — accepts Loki log entries from `loki.*`
  components and emits them as OTLP logs.
- `otelcol.exporter.otlphttp` — sends OTLP over HTTP to the collector.
- `otelcol.processor.batch` — batch before export (compression, fewer
  round-trips); recommended between the two.

## Target pipeline

Replace the `loki.write "local"` block and retarget the two
`forward_to = [loki.write.local.receiver]` references:

```
loki.process "containers"  forward_to → otelcol.receiver.loki.default.receiver
loki.source.file "rtorrent_cleanup" forward_to → otelcol.receiver.loki.default.receiver

otelcol.receiver.loki "default" {
  output { logs = [otelcol.processor.batch.default.input] }
}

otelcol.processor.batch "default" {
  output { logs = [otelcol.exporter.otlphttp.clickstack.input] }
}

otelcol.exporter.otlphttp "clickstack" {
  client {
    endpoint = "http://clickstack-otel:4318"     // bilby: in-network
    headers  = { "authorization" = sys.env("CLICKSTACK_INGESTION_KEY") }
  }
}
```

Notes and edge cases:

- **Ingestion auth.** ClickStack's collector requires the ingestion API
  key. HyperDX/OTel expects it as an `authorization` header. The exact
  header form (raw key vs `Bearer <key>`) must be confirmed against the
  HyperDX *Team Settings → API Keys* help text at bootstrap time — get
  this wrong and ingest silently 401s. The key arrives via the
  bootstrap step in [Stack & storage](clickstack-stack.md): it's a
  `[[VAR]]` from 1Password injected into the Alloy container's
  environment through the `logging` stack's `stack.toml`, read here
  with `sys.env`. **Fail-fast:** if the env var is empty Alloy must
  error, not ship unauthenticated — do not default it.
- **Label → attribute mapping.** Loki labels (`container`, `stream`,
  `compose_project`, `compose_service`, `host`, `service`) become OTLP
  resource/log attributes through the bridge. HyperDX's default `Logs`
  source keys off `ServiceName` / `Body` / `LogAttributes`. Verify the
  bridged attribute names land where HyperDX expects, or set
  `loki.resource.labels` / a `stage.label`→resource mapping so
  `service`/`compose_service` populate `ServiceName`. This is the most
  likely "logs arrive but show blank service" papercut — validate in
  the HyperDX search UI before [cutover](cutover.md), querying for a
  known container (e.g. `flood`, `op-connect-api`).
- **`rtorrent-cleanup`** keeps its distinct `service="rtorrent-cleanup"`
  label so it stays queryable separately — confirm it maps to a
  distinct `ServiceName` in HyperDX.
- **Timestamps.** The bridge preserves entry timestamps; HyperDX's
  default source uses `TimestampTime`. No action expected, but spot-
  check that historical-looking skew isn't introduced for the
  file-tailed source.

## Kangaroo

`logging/kangaroo/alloy-conf/config.alloy` is the same pattern but
writes cross-LAN to bilby's published VL (`10.0.0.119:9428`). After
migration it writes cross-LAN to bilby's published collector OTLP/HTTP:

```
endpoint = "http://10.0.0.119:4318"
headers  = { "authorization" = sys.env("CLICKSTACK_INGESTION_KEY") }
```

This is why [Stack & storage](clickstack-stack.md) publishes `4318` to
the host — kangaroo has no in-network path to the collector.
Edge cases:

- **Same key both hosts.** One ingestion key, referenced from both the
  bilby and kangaroo `logging` overlays' `stack.toml` `environment`
  blocks (same variable name, per the multi-host convention).
- **Cross-LAN over plaintext.** kangaroo→bilby `:4318` is unencrypted
  HTTP over the trusted LAN, exactly as the VL `:9428` path was today.
  Upstream recommends TLS on OTLP; for a LAN-local homelab hop this is
  acceptable (matches the existing posture and the
  "don't overindex on security for personal-scale" reality). Flag, do
  not gold-plate.
- **kangaroo arch.** kangaroo only runs Alloy; the OTLP bridge
  components are pure Alloy and arch-agnostic. No image changes on
  kangaroo.

## Why no dual-ship

The [index](index.md) records the hard-swap decision: Alloy does **not**
fan out to both VL and ClickStack. A fan-out (`forward_to` listing both
`loki.write.local` and the otel bridge) is technically trivial here, but
it was explicitly declined — it complicates the config, doubles ingest
load on a memory-constrained box during the riskiest window, and the
rollback (VL stopped-but-intact) covers the failure case. The shaping
pipeline is shared, so a fan-out would also double-process; not worth
it. See [Cutover](cutover.md) for the swap and rollback mechanics.

## As-built: the ServiceName papercut (resolved 2026-05-16)

The predicted papercut happened exactly as flagged. `otelcol.receiver.loki`
puts the Loki labels (`container`, `host`, `compose_service`,
`compose_project`, `stream`, `service`) into the OTLP log record as
**`LogAttributes`**, and sets **no** `service.name` resource attribute.
ClickStack's `otel_logs` therefore has an empty `ServiceName` column, and
HyperDX's default Logs source (`serviceNameExpression: ServiceName`) shows
every line with a blank service. Logs are *fully ingested and queryable*
by `LogAttributes['container']` etc. — only the default UI grouping is
affected.

**Fix applied:** the HyperDX Logs (and Session) source
`serviceNameExpression` was repointed to `LogAttributes['container']`
(a `db.sources.updateOne` on the `hyperdx` Mongo db). Sources live in
Mongo, so this is durable and is captured by the nightly mongodump
backup. `DEFAULT_SOURCES` in `clickstack/compose.yaml` only seeds at
first-run, so a from-scratch DR rebuild re-creates the source with the
upstream `ServiceName` default — **the DR runbook must re-apply this
Mongo update** (or, the cleaner durable fix, fold it into
`DEFAULT_SOURCES`). The most idiomatic long-term fix is Alloy-side: an
`otelcol.processor.resource`/`transform` stage setting
`service.name` from the `container` attribute before export, which
benefits any OTLP consumer and survives a Mongo wipe — deferred as a
follow-up, not cutover-blocking.

## Validation before declaring done

- HyperDX search returns live lines for `container=flood` and
  `op-connect-api` with the JSON message correctly extracted (not the
  raw JSON envelope) — proves the shaping stages still run. ✅
- ANSI is stripped (komodo-core / flood lines are readable). ✅ (0/82
  komodo-core lines carried escape codes post-cutover)
- `rtorrent-cleanup` events appear under a distinct service —
  ⏳ unverified: it's an erase-event-driven file tail and no torrent
  was erased since cutover (source file mtime predates it). Config is
  unchanged from the VL setup; will flow on the next event.
- kangaroo container logs appear (proves the cross-LAN authed path). ✅
  (`LogAttributes['host']='kangaroo'` rows present)
- Killing the ingestion key (wrong value) makes ingest fail visibly —
  ✅ proven at bootstrap (wrong key → 401, correct key → 200).
