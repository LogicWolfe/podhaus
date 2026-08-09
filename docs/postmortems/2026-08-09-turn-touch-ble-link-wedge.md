# 2026-08-09 — Turn Touch BLE link died silently, with nothing to detect or recover it

**Status:** resolved (open action items)
**Severity:** medium
**Trigger:** sustained multi-button input on the burrow Turn Touch

## Summary

A child spam-pressed all four buttons on the burrow Turn Touch for roughly 50
seconds. Home Assistant kept up the whole time — the Hue bulbs, Nanoleaf Shapes
and fan downlight were still changing state at the last event. Then the remote
stopped transmitting and the BLE link to its ESP32 bridge went down. It stayed
down for **5h09m**, until the remote's battery was physically reseated.

Nothing detected it. The `event` entities that carry button presses are
`template` entities on the ESP32, so they remain `available` for as long as the
ESP32 is up — which it was, the entire time, connected to Home Assistant and
answering its API. No entity went unavailable, no error was logged, and no alert
fired. The only trace anywhere in the system was `sensor.turn_touch_burrow_battery`
going `unknown` at 16:37:46 when its 30-minute GATT read returned NAN, and that
was found by hand while investigating a verbal report, not by any monitoring.

The device also had no observability of its own: ESPHome logs were shipped
nowhere, the logger sat at INFO so the decode trace was not even emitted, and
there was no entity for link state, notification count, signal strength, uptime
or heap. Diagnosis was done entirely by querying Home Assistant's recorder
SQLite database after the fact.

## Timeline

All times AWST.

| Time | Event |
|---|---|
| 08-08 15:38 | Device in service; battery gauge reporting 95% |
| 08-09 15:07 | Battery gauge reads 71% |
| 15:54, 16:03 | Home Assistant restarts (unrelated — West-hold scene fix, `5b0ce62`) |
| 16:19:13 | Button burst begins — ~5 events/sec across all four buttons on a ~200 ms grid |
| 16:20:01.596 | Last event ever received from the remote |
| 16:20:02 | Lights still responding; `light.burrow` changes state after the final button event |
| 16:37:46 | `sensor.turn_touch_burrow_battery` → `unknown`. The 30-minute GATT read returned NAN. This is the only signal the link is gone, and nothing consumes it |
| 18:44 | Verbal report ("it just stopped working"). Investigation begins against the recorder DB |
| 18:45 | Confirmed: no turn-touch entity `unavailable` since 16:03; ESP32 holding two live API connections on `10.0.0.238:6053` |
| 19:52 | Watchdog + diagnostics + Alloy scrape deployed (`785d11e`) |
| 20:10 | First OTA flash. Built from the stale config volume — see Root cause 5 |
| 20:10–20:20 | Device log shows `Connection open error, status=133` (`ESP_GATT_CONN_FAIL_ESTABLISH`) on every attempt |
| ~20:20 | Buttons pressed by hand to wake the remote. `ble_notifications` stays 0 — no advertisement ever reaches the ESP32 |
| 20:25 | Corrected flash; watchdog cadence verified against the metric |
| 21:28:53 | Battery reseated. Link re-establishes |
| 21:29:44–57 | Events received on all four buttons. Service restored |

## Root cause

Five defects, one of which caused the outage and four of which made it last five
hours.

1. **The remote stopped transmitting after sustained input, and only a power
   cycle recovered it.** Every connection attempt failed with
   `ESP_GATT_CONN_FAIL_ESTABLISH` — the peer was not answering. It did not
   respond to button presses either, so it was not advertising at all. Whether
   this is the peripheral's firmware wedging or a power-related fault in the
   remote is **not established**; what is established is that reseating the cell
   fixed it and nothing short of that did.

2. **A dead BLE link is invisible in Home Assistant.** The four `event` entities
   are templates on the ESP32. They report the ESP32's health, not the remote's.
   With the bridge up, they stay `available` forever and the failure presents as
   "buttons do nothing" with no error anywhere.

3. **The only liveness probe ran every 30 minutes and nothing consumed it.**
   The `ble_client` battery sensor publishes NAN on a failed GATT read, which
   surfaces as `unknown` rather than `unavailable`. That distinction was the key
   diagnostic and it existed by accident, not by design.

4. **There was no recovery path.** `esp32_ble_tracker`'s `auto_connect` retried
   throughout and could not help against a silent peer, and nothing else
   escalated, cycled the link, or raised an alert.

5. **The ESPHome container's `/config` is a volume seeded by `esphome-init` at
   deploy time, not a bind mount of the repo.** Compiling straight after editing
   a device YAML silently builds the *previously deployed* config, and the OTA
   reports success because it did upload something. This cost one flash cycle
   during remediation and briefly produced a wrong conclusion about the
   watchdog's behaviour.

## Impact

Burrow Turn Touch non-functional for 5h09m (16:20 → 21:29). Alternate control
paths for the room remained available throughout — the Hue tap (whose rules live
on the bridge, independent of this automation) and the Home Assistant app.

No data loss. No other stack affected. The ESP32 bridge, its wifi link and its
Home Assistant API connection were healthy for the entire incident.

## Resolution

**In-repo**

- [x] **2026-08-09**: BLE link watchdog on connection state, cycling `ble_client` after a sustained disconnect (`785d11e`). Triggering on connection state rather than button activity is deliberate — see What we learned.
- [x] **2026-08-09**: Watchdog threshold corrected 90 s → 5 min with its own dedicated timestamp global (`f1b600c`). The first implementation fired every interval tick, aborting connection attempts still in flight and leaving the GATT client in `DISCONNECTING` when the open event arrived.
- [x] **2026-08-09**: Diagnostic entities — `BLE link`, `BLE notifications`, `BLE last notification age`, `BLE reconnect cycles`, `WiFi signal`, `Uptime`, `Heap free` (`785d11e`).
- [x] **2026-08-09**: ESPHome `prometheus:` endpoint scraped by bilby's Alloy into ClickStack under `service.name = esphome` (`785d11e`).
- [x] **2026-08-09**: UniFi DHCP reservation pinning the scrape target (`terraform/unifi.tf`, applied 2026-08-09).

**Docs**

- [x] **2026-08-09**: `docs/runbooks/ble-remotes.md` — new "Diagnostics and link recovery" section; gotcha recording that a dead link leaves entities `available` and that `unknown` on a `ble_client` sensor is the tell (`785d11e`).
- [x] **2026-08-09**: Flash procedure rewritten CLI-first with the deploy-before-compile ordering trap and the build-memory precaution (`e718fd0`).
- [x] **2026-08-09**: `docs/monitoring.html` ESPHome device metrics section; `AGENTS.md` `iot/` row (`785d11e`).

**Operational**

- [x] **2026-08-09**: Battery reseated; link restored and stable.

**Open**

- [ ] **No alerting.** Metrics exist but nothing pages when `ble_link` reads 0 or `BLE last notification age` grows without bound. Until this lands, detection still depends on somebody noticing the lights don't respond — which is the same position we were in during this incident, just with better forensics afterwards.
- [ ] **Determine whether the remote advertises continuously when disconnected, or only when a button is pressed.** This sets the floor on recovery time and decides whether the watchdog can ever recover this failure class or is only ever a fallback.
- [ ] **Establish the battery discharge trend.** Gauge readings across this incident were 95 / 87 / 71, then 6 and 13 within 21 seconds of each other after the reseat. They are not consistent enough to treat as state of charge. The series is now being collected; draw no conclusions from fewer than 24 h of it.

## What we learned

**An `available` entity is not a working entity.** Where a bridge device
synthesises entities for a sensor it talks to, those entities report the
bridge's health. Every remote bridged this way has the same blind spot, and the
fix is an explicit link-state entity rather than inferring health from the
absence of `unavailable`.

**Only an active probe can distinguish idle from dead.** A passive event stream
cannot: no button presses overnight looks exactly like a wedged remote. This is
also why the watchdog triggers on connection state rather than on time-since-last-press
— a press-timeout watchdog would have to cycle the link on a schedule through
every quiet night, spending a coin cell to prove liveness, while connection
state is a local variable on a mains-powered ESP32 and costs the remote nothing.

**For embedded devices, metrics are worth more than logs.** The question that
needed answering — is the link up, is the remote transmitting — is state, and
state is cheap to export and cheap to store. Shipping ESPHome's log lines would
have required a broker plus a bridge process (neither Alloy nor the OTel
collector has an MQTT source) and would not have answered it any better.

**A build that reads a deployed artifact will silently consume stale input.**
The upload's success message validates the transfer, not the source. Where a
build step reads from anywhere other than the working tree, the ordering
constraint belongs in the runbook next to the command.

## Out of scope

- **Shipping ESPHome logs to HyperDX.** Rejected: ESPHome has no syslog output, and the MQTT route needs a broker plus a Telegraf bridge — two new services to carry log lines worth less than the entity state now being exported.
- **Scraping Home Assistant's `/api/prometheus`.** Rejected for now. It would cover every entity in the house from one target, but bilby's ClickHouse runs under a 4 GB cap and the device-side scrape is ~10 series against several hundred.
- **Battery replacement as the remedy.** The cell was days old. The reseat's effect was to power-cycle the remote, not to restore charge.

## Related

- [BLE remotes runbook](../runbooks/ble-remotes.md) — diagnostics, watchdog design, flash procedure
- [Monitoring](../monitoring.html) — ESPHome device metrics in the pipeline
- [2026-08-08 — bilby OOM session teardown](2026-08-08-bilby-oom-session-teardown.md) — an ESPHome build was that incident's trigger, and is why the flash procedure now carries a memory precaution
