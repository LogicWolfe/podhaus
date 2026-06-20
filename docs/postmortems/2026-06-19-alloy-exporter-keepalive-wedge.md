# 2026-06-19 — kangaroo Alloy exporter wedged silently after the ClickStack collector recreated

**Status:** Resolved
**Severity:** Medium
**Trigger:** ClickStack collector (`clickstack-otel`) container recreate

## Summary

The *Kangaroo Log Ingest (staleness)* Gatus check fired: no kangaroo logs
had reached ClickHouse for 68 minutes. kangaroo's Alloy OTLP exporter had
silently stopped shipping — the container was running, healthy, attached
to dockernet, and could reach the collector (`TCP_OK` to
`10.0.0.119:4318`), with **zero error logs**. The silence was the
signature.

Root cause: kangaroo pushes cross-LAN to a **fixed IP behind bilby's
published `:4318` + NAT**. When the `clickstack-otel` collector container
recreated earlier that day (a `clickstack/` edit bumped the whole stack's
content hash, recreating every service including the collector), the IP
stayed the same but the backend container didn't — kangaroo's existing
keepalive TCP connection stayed mapped through conntrack to the now-dead
container, so the next send **blackholed and hung silently** (no RST).
`retry_on_failure { max_elapsed_time = "0s" }` (retry forever) — itself a
prior fix for a *different* wedge mode — then made it permanent: the queue
consumers retried a request that never returns, never failing, never
giving up.

bilby never wedges from the same collector recreate because it ships
**in-network by container name** (`clickstack-otel:4318`) — Docker DNS
re-resolves to the new container. That asymmetry was the diagnostic key.
No service impact (logging only); the 68 minutes of kangaroo logs in the
gap were generated but never shipped and are absent from ClickStack.

## Timeline

Times AWST (= UTC+8).

| Time (AWST) | Event |
|---|---|
| ~09:00 | Push `1365355` redeploys clickstack — a `mongo-dump.sh` edit bumped the whole `clickstack/` content hash, recreating all four services including the `clickstack-otel` collector (the stack-level hash coarseness). |
| 09:36 | kangaroo Alloy logs `context deadline exceeded` to `10.0.0.119:4318/v1/traces` during the collector turbulence, then recovers and ships normally. |
| 14:32 | kangaroo logs stop reaching ClickHouse — the silent wedge. No alloy error logs from here on (just its 4-hourly stats ping). |
| 15:40 | *Kangaroo Log Ingest (staleness)* alert fires (60+ min stale). |
| 15:40–15:41 | Diagnosed: exporter wedge (running/healthy/reachable, silent — not the phantom-network class). `docker restart alloy` → shipping resumes (144 rows in 3 min). |
| ~15:55 | Root-caused: the retry-forever config was active (not drift), so this was a deeper hang than retry-give-up. bilby-by-name vs kangaroo-by-fixed-IP asymmetry pinned the NAT/keepalive mechanism. |
| ~16:18 | Fix deployed (`af70f52`): `disable_keep_alives = true` + bounded 30 m retry on kangaroo + kookaburra `config.alloy`. Verified loaded on both hosts. |
| ~16:22 | Validated: force-recreated `clickstack-otel` (new container, the exact trigger); kangaroo shipped straight across it (generated logs landed in ClickHouse in ~24 s, zero export errors). |

## Root cause

Three compounding defects:

1. **Cross-network push to a fixed IP behind NAT.** kangaroo/kookaburra
   target `bilby:4318` (a published port → DNAT to the collector
   container). A collector *recreate* leaves the host's `:4318` DNAT
   pointing at a new container while the client's keepalive TCP
   connection is still tracked (conntrack) to the dead one. Packets on
   that connection are blackholed with no RST, so the send **hangs
   silently** rather than erroring. bilby avoids this entirely by
   addressing the collector by container name (DNS re-resolves on
   restart).

2. **`max_elapsed_time = "0s"` (retry forever) made the hang permanent.**
   This was a deliberate earlier fix for the *opposite* wedge — OTel's
   default retry giving up after 5 min and the queue stalling. But
   infinite retry on a request that never *returns* (the hung
   connection) means the queue consumers loop forever without failing or
   succeeding: a permanent, silent wedge. The resilience fix traded a
   loud give-up for a silent eternal hang.

3. **Nothing local could detect it.** The port-only `:12345` healthcheck
   reads healthy through a wedge, so autoheal never fires. And on a
   low-volume host like kangaroo the in-container exporter metrics
   (`queue_size`, `sent_*_total`) look identical whether wedged or merely
   quiet — the same volume floor that forces the 60-min staleness window.
   The end-to-end ClickHouse staleness check is the only reliable
   detector, which is why fixing the cause beat bolting on any auto-heal.

## Impact

- **No data loss beyond the gap.** 68 minutes of kangaroo container logs
  (14:32–15:40) were generated but never shipped — they sat in the
  in-memory queue and were dropped on the restart, so they're absent from
  ClickStack. No application data, no backups, no service availability
  affected (logging pipeline only).
- **bilby and kookaburra unaffected** throughout.

## Resolution

### In-repo

- [x] **2026-06-19**: `disable_keep_alives = true` + `retry_on_failure
  { max_elapsed_time = "30m" }` on both cross-network exporters
  (`logging/kangaroo/alloy-conf/config.alloy`,
  `logging/kookaburra/alloy-conf/config.alloy`), commit `af70f52`. A
  fresh connection per batch always reaches the current collector; the
  bounded retry frees the queue if a batch is ever genuinely stuck.
  Per-batch connection overhead is negligible at these hosts' volume.
  bilby is left as-is — DNS re-resolution already protects it.
- [x] **2026-06-20**: replaced the kangaroo *Kangaroo Log Ingest
  (staleness)* detector itself. The old check proxied pipeline liveness
  off organic kangaroo log volume, but kangaroo is low-volume enough that
  its quiet gaps drifted above any fixed window (60 → 150 min, still
  false-firing — organic gaps reached 152 and 170 min within days). Fixed
  by stamping a stable `host` resource attribute on Alloy's 60 s
  self-metric scrape (`svc_alloy` transform, bilby + kangaroo
  `config.alloy`) and repointing the Gatus check at a 15-min heartbeat
  over `otel_metrics_gauge` where `host='kangaroo'`. The self-metric is a
  fixed cadence on the same exporter as the logs, so it detects the wedge
  / phantom-network classes in ~10 min instead of 150 with zero false
  positives — and per-host pipeline metrics (queue depth, sent totals,
  retries) are now queryable, the observability that was missing during
  this investigation. (kookaburra has no self-metrics scrape, so it's
  unchanged.)

### Documentation

- [x] **2026-06-19**: `docs/monitoring.html#known-issues` — exporter-wedge
  entry updated to root-cause-fixed (`fb306cd`), with `RestartStack
  kangaroo-logging` retained as the fallback.
- [x] **2026-06-19**: this postmortem + index + AGENTS.md entry.

### Operational

- [x] **2026-06-19**: recovered the active incident with `docker restart
  alloy` on kangaroo.
- [x] **2026-06-19**: validated the fix by force-recreating
  `clickstack-otel` and confirming kangaroo shipped across the recreate.

## What we learned

- **A resilience fix can introduce a worse failure mode.** Retry-forever
  is the documented OTel infinite-retry footgun; here it converted a
  recoverable connection blip into a permanent *silent* wedge. Prefer a
  long-but-bounded retry over `0s`.
- **Cross-network push to a fixed IP behind NAT is the fragile pattern.**
  A backend container recreate poisons a keepalive connection silently;
  addressing the backend by DNS name (which re-resolves) is resilient.
  When only *some* hosts wedge, look at how each one addresses the
  endpoint — the asymmetry is the clue.
- **Low-volume hosts can't be wedge-detected in-container.** The local
  metrics can't tell wedged from quiet, so neither a smarter healthcheck
  nor autoheal can catch it; the end-to-end staleness check is the only
  honest signal. Fixing the cause is better than auto-healing a symptom
  you can't reliably detect.
- **The content-hash coarseness has a downstream cost.** Recreating the
  collector on any `clickstack/` edit is what triggered this. Collectors
  should survive restarts — which the fix now ensures — so the coarseness
  stays an accepted trade-off rather than a latent hazard.

## Out of scope

- **A second auto-heal mechanism** (a scheduled end-to-end watchdog that
  `RestartStack`s a stale `<host>-logging`) was designed and **declined**:
  fixing the root cause removed the need, and a docker-healthcheck /
  autoheal path can't reliably detect this wedge on a low-volume host.
  Reopen only if a *different*, unfixable wedge mode appears. (What did
  land on 2026-06-20 was not auto-heal but a better *detector* — the
  self-metric heartbeat above — which makes the staleness alert honest
  on a low-volume host rather than trying to self-heal a symptom.)

## Related

- `logging/{kangaroo,kookaburra}/alloy-conf/config.alloy` — the fix, with
  inline rationale.
- `docs/monitoring.html#known-issues` — wedge-vs-phantom-network triage +
  the fallback runbook.
- [OpenTelemetry Collector resiliency](https://opentelemetry.io/docs/collector/resiliency/)
  and the [exporterhelper README](https://github.com/open-telemetry/opentelemetry-collector/blob/main/exporter/exporterhelper/README.md)
  — the infinite-retry / sending-queue behaviour.
- `docs/postmortems/2026-06-16-firmware-reboot-recovery.md` — a *separate*
  kangaroo Alloy wedge earlier the same day (phantom dockernet + detach),
  distinct root cause.
