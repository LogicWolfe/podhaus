# Gatus → Fenwick notifications + status-page grouping

Two related pieces of work on the Gatus monitoring stack, started
2026-06-19:

1. **Status-page retention + service grouping** — edits complete, not
   yet deployed.
2. **Route alerting through Fenwick** (Signal, agent-decided) instead of
   Postmark — designed, not yet built.

---

## Done so far (in the working tree, undeployed)

### Retention fix

`gatus/conf/config.yaml` storage block used a non-existent key
`capping: 65000`, silently ignored by Gatus's lenient YAML parser — so
retention sat at the defaults (100 results, ~3 h at 2 m intervals)
despite the comment claiming 90 days. Fixed to the real keys:

- `maximum-number-of-results: 65000` — ~90 days of per-endpoint probe
  history. Consumed by the **endpoint-detail page** (paginated, 50/page)
  and the API, *not* the home strip (front-end-capped at ~50 boxes).
- `maximum-number-of-events: 10000` — the detail page's **Events
  timeline** (status transitions); default 50 truncated incident history
  on flappy endpoints. One tiny row per transition.

Neither affects alerting (driven by live thresholds) or HyperDX
retention. Larger history only accrues from deploy forward — no
backfill.

### Service-primary grouping

Regrouped all 30 endpoints from the old flat `services` / `heartbeat`
buckets to **service-primary** groups (host stays an axis only where the
thing *is* a host or a cross-host service). 15 groups:

| Group | Members |
|---|---|
| Komodo | Komodo, Bilby Periphery, Kangaroo Periphery, Komodo Alerts |
| Backup | Backrest bilby + kangaroo, Backrest Nightly, Backrest Kangaroo Nightly, Backrest Pets |
| Observability | HyperDX, Pipeline Log Ingest, Kangaroo Log Ingest, ClickStack Mongo Dump |
| Torrents | Flood, RAR Extraction, Pinelake Stignore |
| Plex | Plex, Plex Stats Cleanup |
| Storage | MinIO on-bilby, MinIO via relay |
| Yiayia | Frontend, Device |
| Kangaroo | Kangaroo (NAS) — the QNAP box itself |
| Pets · Syncthing · Paperless · Home Assistant · Mumble · UniFi · nathanbaxter.com | one endpoint each |

Decisions baked in: both Peripheries live under **Komodo** (the service),
not a kangaroo host group; **Backup** holds all backrest incl. the Pets
heartbeat; **ClickStack Mongo Dump** sits under Observability;
**nathanbaxter.com** is its own group, not folded into Storage.

**The coupled part — push-endpoint keys.** A Gatus external-endpoint's
push key is `<group>_<name>` (lowercased, with `/ _ . , space # + &` →
`-`). Moving the 7 heartbeats out of `heartbeat` changed their keys, so
every sender was updated in lockstep:

| New key | Sender updated |
|---|---|
| `backup_backrest-nightly` | `backup/bilby/stack.toml` |
| `backup_backrest-pets` | `backup/bilby/stack.toml` |
| `backup_backrest-kangaroo-nightly` | `backup/kangaroo/stack.toml` |
| `torrents_rar-extraction` | `flood/scripts/rar-backlog.sh` |
| `torrents_pinelake-stignore` | `flood/scripts/pinelake-stignore.sh` |
| `observability_clickstack-mongo-dump` | `clickstack/scripts/mongo-dump.sh` |
| `plex_plex-stats-cleanup` | `plex/scripts/stats-cleanup.sh` |

Comments referencing the old keys (in the above + `flood/compose.yaml`,
`plex/compose.yaml`, `clickstack/compose.yaml`,
`docs/runbooks/flood.html`) were updated too. `docs/monitoring.html`'s
"adding a monitor" section now describes the service-primary convention.

### Rollout caveats for the grouping deploy

- **Key change resets per-endpoint history.** Each moved heartbeat is a
  *new* endpoint in Gatus's eyes — its old results/events are dropped and
  last-seen resets. For the long-interval ones (esp. **Plex Stats
  Cleanup**, 768 h) seed a baseline after deploy by POSTing one success
  to the new key, or just accept it'll establish on the job's next run.
- **Transient push failures during rollout.** Between the gatus redeploy
  (new keys live) and the sender stacks' redeploy, pushes to the changed
  keys 404 (logged as WARN by each sender, non-fatal). Self-heals once
  both sides land in the same Stage-2 batch.
- **Pinelake monitoring plan** (`docs/plans/pinelake-migration/`) still
  describes its own `backup-pinelake` group naming — reconcile with this
  service-primary convention when pinelake lands.

---

## Pending: route alerting through Fenwick

**Goal.** Replace the Postmark email alerter with a push to Fenwick, and
let Fenwick (the Signal/email home-helper agent) decide how to notify —
under household guidance. An LLM call per alert is the point: Fenwick can
start simple ("just notify me") and grow to "notify on the first alert
for a service, then aggregate" without code changes, only guidance.

### Fenwick side (new code, in the `fenwick` repo)

- **A new injectable source event type** — e.g. `service_alert` — added
  alongside `signal_message` / `email_arrival` / `schedule_fired`:
  - union + `INJECTABLE_TYPES` / `isInjectableType` in `src/events/`
  - payload schema + brand-wrap in `src/channels/http/injectable.ts`
    (straw-man payload: `service`, `group`, `status`
    triggered/resolved, `description`, `errors`, `conditions`)
  - a handler mirroring `src/handlers/schedule-fired-handler.ts` that
    runs the agent on the event
  - an `eventToolMap` row scoping its tools: `SendSignalMessageTool`
    (notify) + `ReadActivityLogTool` (dedup) + `CreateScheduleTool`
    (time-windowed batching)
- **Reuse the existing `/events` transport** — no per-type endpoints.
  Trusted senders authenticate with the shared
  `FENWICK_INTERNAL_HTTP_TOKEN`; the principal is auth-derived, so Gatus
  presents `X-Fenwick-User: Nathan` and the alert triages in the admin
  context with admin guidance.
- **Preseed guidance** for the new event type = "notify me." Iterate
  later toward first-alert-then-aggregate (read activity log to dedup;
  schedule a follow-up summary so a quiet period still closes out).

### Gatus side (config only)

- Repoint the `custom` alerter at `http://fenwick:8088/events/async`
  (async 202 — don't block Gatus's HTTP client on an LLM round-trip),
  with `Authorization: Bearer ${FENWICK_INTERNAL_HTTP_TOKEN}` +
  `X-Fenwick-User: Nathan`, body templated as `{type: "service_alert",
  payload: {…}}` from Gatus's `[ENDPOINT_NAME]` etc. placeholders.
- Add `FENWICK_INTERNAL_HTTP_TOKEN` to `gatus/stack.toml` (same 1P
  source Fenwick uses: `OP__KOMODO__FENWICK_INTERNAL_TOKEN__CREDENTIAL`)
  and map it through `gatus/compose.yaml`.

### The Postmark backstop (decided: keep it, narrowly)

Putting the agent in the alert path means a Fenwick / signal-cli / LLM
outage makes alerts silently vanish. So the **fenwick-health checks
specifically** keep alerting via Postmark — they must not route through
the thing they're watching. Mechanism: Gatus supports multiple alerter
types; each endpoint picks via its `alerts:` list.

- `custom` alerter → Fenwick (default for everything via the `*alerts`
  anchor).
- `email` alerter → Postmark **SMTP** (`smtp.postmarkapp.com:587`, the
  existing `POSTMARK_SERVER_TOKEN` as both username and password — the
  current Postmark path is the HTTP-API `custom` alerter, which we're
  giving to Fenwick, so Postmark moves to the native `email` type).
- **New** fenwick-health endpoints (the `fenwick` container `/health`,
  the `signal-cli-rest-api` sidecar, optionally an end-to-end send)
  carry `alerts: [- type: email]`. None exist today.

### Open decisions before building Fenwick

1. Event type name (`service_alert`?).
2. Exact payload contract Gatus sends.
3. Which fenwick-health probes to add for the Postmark backstop.

---

## Deploy order (when authorized)

Grouping + retention and the Fenwick switch can ship separately. For the
grouping/retention deploy: one `git push` (or `./komodo-sync`) — Stage-2
redeploys gatus + the touched sender stacks (backup, flood, clickstack,
plex) in one batch, so the key change and the sender updates land
together. Then seed the long-interval heartbeat keys. Nothing here is
deployed yet — awaiting green light.
