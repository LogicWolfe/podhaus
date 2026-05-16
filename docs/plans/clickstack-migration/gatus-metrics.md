# Gatus metrics

"Wire gatus metrics into it too." Gatus today exposes **no metrics** —
it's pure endpoint + heartbeat + Komodo-API monitoring with Postmark
email alerts, and its history is read by Grafana's Infinity datasource
against the Gatus API. ClickStack changes both ends: Gatus *can* expose
Prometheus metrics, and with Grafana retired, the uptime view must move.

## Enabling Gatus metrics

Gatus has a built-in Prometheus exporter, off by default. It's a
one-line addition to `gatus/conf/config.yaml`:

```yaml
metrics: true
```

This exposes `/metrics` on the existing `:8080` (the same port the UI
and external-endpoint hooks use — no new port, no new ingress).
Gatus's metric series include per-endpoint result counts, response
time, certificate expiry, and result code — enough to chart uptime and
latency and to alert on. This is a low-risk config change; the only
caution is that `/metrics` is now reachable by anything on dockernet
(acceptable — it's non-sensitive operational data on the trusted
network; the public `gatus.pod.haus` path is still Access-gated and
`/metrics` need not be added to the tunnel ingress).

## Getting metrics into ClickHouse

The ClickStack bundled collector is **opinionated and OpAMP-managed** —
it's built for OTLP ingest, not for scraping arbitrary Prometheus
endpoints, and fighting its managed config to add a `prometheus`
receiver is brittle across `IMAGE_VERSION` bumps. We already have a
clean OTLP producer on the same network: **Alloy**. Use it.

Alloy on bilby gains a scrape + convert + export path alongside the log
pipeline ([Ingestion pipeline](ingestion-pipeline.md)):

```
prometheus.scrape "gatus" {
  targets    = [{ __address__ = "gatus:8080", __metrics_path__ = "/metrics" }]
  forward_to = [otelcol.receiver.prometheus.default.receiver]
}

otelcol.receiver.prometheus "default" {
  output { metrics = [otelcol.processor.batch.default.input] }
}
```

The same `otelcol.processor.batch` → `otelcol.exporter.otlphttp`
(authed, to `clickstack-otel:4318`) tail already built for logs carries
the metrics. The collector writes them into ClickStack's
`otel_metrics_*` tables, and HyperDX's default `Metrics` source already
points there — no new source wiring in HyperDX.

Edge cases:

- **Same authed exporter, same ingestion key** — metrics ride the
  log pipeline's OTLP exporter; no second key, no second endpoint.
- **`gatus:8080` is in-network** — bilby Alloy reaches Gatus by
  container name on dockernet; no host publish needed (Gatus already
  joins dockernet).
- **Scrape interval vs Gatus check interval.** Gatus checks at
  60 s–2 m; scraping faster than Gatus updates just resamples stale
  values. Match the scrape interval to Gatus's cadence (~60 s).
- **Metric cardinality → retention.** Per-endpoint × per-result-code
  series are modest here (~15 endpoints) but feed the metrics-table
  TTL sizing in [Retention & storage](retention-and-storage.md).
- This is **net-new** signal — VL never stored metrics — so it's purely
  additive and can't regress anything that exists today.

## The uptime view, after Grafana

Decision recorded in the [index](index.md): **Grafana is retired
entirely.** Today Grafana provides (a) the log explorer via the VL
datasource — *replaced by HyperDX natively*, and (b) the **Uptime
Status** dashboard via the Infinity datasource hitting the Gatus API —
*this has no automatic replacement* and must be deliberately rebuilt.
Options:

1. **Rebuild as a HyperDX dashboard** over the new `otel_metrics_*`
   Gatus series (uptime %, latency, recent failures, cert expiry).
   Recommended — single pane, and richer than the Infinity table once
   the metrics flow.
2. **Lean on Gatus's own status page** (`gatus.pod.haus`) for
   at-a-glance uptime and use HyperDX only for drill-down. Less work,
   loses the single-pane goal, but the Gatus page already exists and
   is Access-gated.

Either way, **alerting does not move**: Gatus's Postmark email alert
chain (`failure-threshold: 3`, `success-threshold: 2`,
`send-on-resolved`) and its push-heartbeat endpoints (Backrest nightly
×2, RAR extraction) are independent of the metrics path and **stay
exactly as they are**. Per memory, do not propose LLM-enriched alert
pipelines; the value of Gatus metrics in ClickHouse is *visualization
and ad-hoc query*, not replacing the existing alert route. HyperDX
alerts on the Gatus metrics would be **additive** and optional, not a
replacement for the Postmark chain.

## Knock-on cleanup when Grafana goes

Tracked in detail in [Cutover](cutover.md); listed here so this stream
is self-contained:

- `grafana.pod.haus` tunnel ingress + DNS + Access policy removed
  (`cloudflare/` Terraform — `tf plan` only without authorization).
- The `grafana` service, `grafana-data` volume, and
  `grafana-provisioning` bind removed from `logging/bilby/compose.yaml`;
  the `victoriametrics-logs-datasource` / Infinity plugin install env
  goes with it.
- Backrest's `logging_grafana-data` external volume + bind removed from
  `backup/bilby/compose.yaml` and the relevant plan
  (see [Backup & DR](backup-and-dr.md)).
- `docs/monitoring.html` rewritten — Grafana is no longer in the
  picture; HyperDX + Gatus are. The provisioned dashboards JSON under
  `logging/bilby/grafana-provisioning` becomes dead and is deleted.

## Validation before declaring done

- `curl gatus:8080/metrics` from an Alloy-network container returns
  Prometheus text.
- A Gatus endpoint series is queryable in HyperDX's Metrics source.
- Forcing a monitored endpoint down moves the metric *and* still sends
  the existing Postmark email (proves the alert chain is untouched).
- The rebuilt uptime view (option 1 or 2) shows current status for all
  ~15 endpoints + the heartbeat endpoints.
