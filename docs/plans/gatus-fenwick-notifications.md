# Gatus → Fenwick notifications

Route Gatus alerting through Fenwick (Signal, agent-decided) instead of
Postmark email. The status-page retention + service-grouping work that
preceded this shipped 2026-06-19 — see *Done* below; the live work is the
Fenwick switch.

---

## As-built (2026-06-19)

Both sides shipped. The design below is accurate to what was built;
deviations and as-built facts:

- **Fenwick `service_alert`** — built TDD, full `deno task check` gate
  green (374 tests), live in `fenwick` origin/main (rode in under the
  other agent's `affb994`, which includes it). Verified: the running
  container recognises `service_alert` over `/events` (a malformed
  inject returns 400 "invalid payload", not 422 "not injectable").
- **Tool scope deviation:** the `service_alert` eventToolMap row scopes
  `send_signal_message` + `read_activity_log` only — **`create_schedule`
  was deferred** (the plan listed it for the aggregation iteration).
  Reason: the codebase convention is tools arrive red-first with the
  behaviour that needs them, and the sibling `schedule_fired` row
  deliberately excludes it as "a runaway surface." The aggregation
  iteration ("notify once, then batch") adds it then.
- **Guidance preseed:** a `service_alert = "notify me"` BOOTSTRAP_ROW was
  added (matches the `email_arrival` precedent). It seeds on
  email-manager registration, so it auto-applies to *new* accounts; the
  existing admin gets the same default behaviour from the handler
  instruction (which says "notify the member with the alert") and can
  author explicit guidance via chat. No retroactive seed was forced.
- **Token env-name:** Fenwick's container exposes the secret as
  `INTERNAL_HTTP_TOKEN` (the compose strips the `FENWICK_` prefix).
  Irrelevant to the wire contract — Gatus sends its own
  `${FENWICK_INTERNAL_HTTP_TOKEN}`, and both stacks resolve the *same*
  1P value (`OP__KOMODO__FENWICK_INTERNAL_TOKEN__CREDENTIAL`), so the
  bearer matches regardless of per-container var name.
- **Gatus side** (this commit): `custom` alerter → `fenwick:8088/
  events/async` with the bearer + `X-Fenwick-User: Nathan`; `email`
  (Postmark SMTP) added as the Fenwick-health backstop; new `Fenwick`
  group = `/health` liveness + the 24h Signal-delivery ClickHouse check,
  both `type: email`. `FENWICK_INTERNAL_HTTP_TOKEN` wired into
  stack.toml + compose.

---

## Done (shipped & validated 2026-06-19)

- **Retention fix** — `gatus/conf/config.yaml` used a non-existent
  `capping` key (silently ignored, retention stuck at the ~3 h default).
  Replaced with `maximum-number-of-results: 65000` (~90 d detail-page +
  API history) and `maximum-number-of-events: 10000` (the detail-page
  Events timeline).
- **Service-primary grouping** — all endpoints regrouped from the flat
  `services` / `heartbeat` buckets into service groups (Komodo, Backup,
  Observability, Torrents, Plex, Storage, Yiayia, + per-service
  singletons). Every push-client's endpoint-ID was updated in lockstep
  (push key = `<group>_<name>`). Convention now documented at
  `docs/monitoring.html#adding-monitor`.
- **Kookaburra coverage** — added *Kookaburra Periphery* (GetServerState
  == Ok, group Komodo) and *Kookaburra Log Ingest* (30-min staleness,
  group Observability). Both live and green.

Deploy reconciled; all polled endpoints green; heartbeats verified on
their new keys (Plex Stats Cleanup seeded manually). Nothing outstanding.

---

## Goal (remaining work)

Replace the Postmark email alerter with a push to Fenwick, and let
Fenwick (the Signal/email home-helper agent) decide how to notify — under
household guidance. An LLM call per alert is the point: Fenwick starts
simple ("just notify me") and grows to "notify on the first alert for a
service, then aggregate" by editing guidance, not code.

### Fenwick side (new code, in the `fenwick` repo)

- **New injectable source event type `service_alert`**, alongside
  `signal_message` / `email_arrival` / `schedule_fired`:
  - union + `INJECTABLE_TYPES` / `isInjectableType` in `src/events/`
  - payload schema + brand-wrap in `src/channels/http/injectable.ts`
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
- **Preseed guidance** for the event type = "notify me." Iterate later
  toward first-alert-then-aggregate (read activity log to dedup; schedule
  a follow-up summary so a quiet period still closes out).

### Gatus side (config only)

- Repoint the `custom` alerter at `http://fenwick:8088/events/async`
  (async 202 — don't block Gatus's HTTP client on an LLM round-trip),
  with `Authorization: Bearer ${FENWICK_INTERNAL_HTTP_TOKEN}` +
  `X-Fenwick-User: Nathan`, body templated as `{type: "service_alert",
  payload: {…}}`.
- Add `FENWICK_INTERNAL_HTTP_TOKEN` to `gatus/stack.toml` (same 1P
  source Fenwick uses: `OP__KOMODO__FENWICK_INTERNAL_TOKEN__CREDENTIAL`)
  and map it through `gatus/compose.yaml`.

### The Postmark backstop (decided: keep it, narrowly)

Putting the agent in the alert path means a Fenwick / signal-cli / LLM
outage makes alerts silently vanish. So the **fenwick-health checks
specifically** keep alerting via Postmark — they must not route through
the thing they're watching. Gatus supports multiple alerter types; each
endpoint picks via its `alerts:` list.

- `custom` alerter → Fenwick (default for everything via the `*alerts`
  anchor).
- `email` alerter → Postmark **SMTP** (`smtp.postmarkapp.com:587`, the
  existing `POSTMARK_SERVER_TOKEN` as both username and password — the
  current Postmark path is the HTTP-API `custom` alerter, which we're
  giving to Fenwick, so Postmark moves to the native `email` type).
- **New `Fenwick` group of health endpoints**, all alerting via `email`:
  - **Signal delivery (24h)** — *the centerpiece.* gatus queries
    ClickHouse (same pattern + creds as the existing log-ingest staleness
    checks) for ≥1 successful `/v2/send` by Fenwick in the last 24h:
    `countIf(SpanAttributes['http.response.status_code']='201') > 0` over
    `otel_traces WHERE ServiceName='fenwick' AND url.full LIKE
    '%/v2/send%'`. Zero → email alert. Catches the silent-Signal-failure
    class end-to-end (a failed send never produces a 201) with **no
    Fenwick code** — the send is already auto-instrumented as an outbound
    HTTP span. Reliable because Fenwick's daily Signal digest guarantees a
    daily send (verified ≥6 successful sends/day across the last 8 days,
    never a zero-day). Detects send-*accepted* (201 = handed to the Signal
    server), not phone-delivered.
  - **Fenwick liveness** — `GET fenwick:8088/health` (returns `ok`), for
    minutes-not-hours detection of a hard container-down (the 24h check
    catches it too, but slowly).

---

## Decisions

1. **Event type name** — ✅ `service_alert`.
2. **Payload contract** — ✅ `{ service, group, status (triggered/
   resolved), description, errors, conditions }`, mapped from Gatus's
   `[ENDPOINT_NAME]` / `[ENDPOINT_GROUP]` / `[ALERT_TRIGGERED_OR_RESOLVED]`
   / `[ALERT_DESCRIPTION]` / `[RESULT_ERRORS]` / `[RESULT_CONDITIONS]`.
3. **Which fenwick-health probes for the Postmark backstop** — ✅
   Resolved: a 24h **Signal-delivery** check (the ClickHouse
   `/v2/send`-success query, detailed in the backstop section above) as
   the primary end-to-end backstop, plus a cheap Fenwick `/health`
   liveness probe for fast container-down detection. Both alert via
   `email` (Postmark). **No daily heartbeat needed** — the existing daily
   Signal digest guarantees the 24h window is populated (verified ≥6
   successful sends/day over the last 8 days, never zero). Sidecar
   liveness + registration-assertion dropped as redundant (a dead or
   deregistered sidecar surfaces as zero successful sends). **Deferred:**
   true delivery-receipt tracking — the only thing that catches
   "accepted-201-but-never-arrived"; Fenwick doesn't consume receipts
   today, so revisit only if a future incident is that class rather than a
   failed send. **Known residual:** a Claude API outage isn't probed
   (notification needs the LLM call) — accepted at personal scale.

---

## Deploy order

Fenwick-side and Gatus-side ship independently of each other but want
coordinating: the `custom`-alerter repoint should land only once the
`service_alert` handler + guidance are live in Fenwick, else alerts hit a
404 / unhandled type. Sequence: build + deploy Fenwick (new event type,
preseeded guidance) → add the fenwick-health endpoints + move Postmark to
the `email` alerter (Gatus) → repoint `custom` at Fenwick (Gatus). Each is
a normal push-to-deploy.
