# BLE remotes

Battery BLE remotes bridged into Home Assistant by ESP32-C3 boards running
ESPHome. The ESP32 subscribes to the remote's GATT notifications, decodes them,
and fires HA `event` entities. All behaviour — which button does what — lives in
Home Assistant, not in firmware.

One ESP32 per remote. They are not shared: each board is pinned to a single MAC.

## Topology

- **`iot/esphome/`** — the ESPHome dashboard stack on bilby. `network_mode: host`
  is load-bearing: the dashboard needs mDNS to discover devices and reach them
  for OTA, and mDNS does not cross the dockernet bridge.
- **`esphome-init`** seeds the config volume from `iot/esphome/config/` and
  renders `secrets.yaml` from Komodo Variables, then exits 0 — hence
  `ignore_services` in `stack.toml`. The repo stays the source of truth; no
  secret is ever written into the checkout.
- **Device YAMLs are flat** in `iot/esphome/config/`, one per physical device.
  The dashboard only lists configs at its config root, so they cannot be
  organised into subdirectories.
- **Dashboard** is LAN-only on `bilby:6052`. It is not behind Caddy or Pomerium.

Secrets come from the 1Password Homelab item **ESPHome**, auto-synced by
komodo-op as `OP__KOMODO__ESPHOME__{WIFI_SSID,WIFI_PASSWORD,API_KEY,OTA_PASSWORD}`.
The API key is the load-bearing one: Home Assistant stores it in its config
entry, so rotating it in 1Password silently breaks the integration until the
entry is re-added.

## Devices

| Device | Remote | BLE MAC | Config |
|---|---|---|---|
| `turn-touch-burrow` | Turn Touch, nickname `burrow` | `D0:B3:F2:63:CE:08` | `iot/esphome/config/turn-touch-burrow.yaml` |

Turn Touch MACs are static random (first octet `0xD0`) and survive a battery
pull, so binding to the MAC is safe.

## Turn Touch protocol

Service `99c31523-dc4f-41b1-bb04-4e4deb81fadd`, characteristic `99c31525`,
two bytes, **notify only**.

Byte 0 is an active-low bitmask in **N, E, W, S order** — not compass order:

| | North | East | West | South |
|---|---|---|---|---|
| press | `fe` | `fd` | `fb` | `f7` |
| double | `ef` | `df` | `bf` | `7f` |

Idle is `ff 00`. Byte 1 = `0xff` means hold. Combinations work (`fc` = N+E,
`f3` = W+S) and are single-press only. Verified against the constants in
`github.com/antsar/python-turntouch`.

**Never poll this characteristic.** A GATT read returns something unrelated to
button state (`0x40eb` at rest), which the decode reads as four buttons down
plus three double-taps. The sensor sets `update_interval: never` for exactly
this reason. Battery (`0x2a19`) *is* a real integer percent and is polled at
30 min; the gauge re-samples and settles rather than tracking continuously.

The decode lives in the sensor's value `lambda:`, not `on_notify` — raw
`std::vector<uint8_t>` is only available in the lambda, whereas `on_notify`
receives the parsed float.

## Diagnostics and link recovery

Each device exposes its entities as OpenMetrics at `http://<device>/metrics`
via ESPHome's `prometheus:` component (which requires `web_server:`). Bilby's
Alloy scrapes that endpoint every 60 s and bridges it into ClickStack, so
device state is queryable in HyperDX under `service.name = esphome`, with
`instance` separating devices.

The scrape targets an IP, not a name: Alloy resolves through Docker's resolver,
which has no mDNS, so `<device>.local` is unreachable from the container. The
address is held by a UniFi DHCP reservation in `terraform/unifi.tf`. **Adding a
device means adding a reservation, a `local`, and a scrape target** — otherwise
the first DHCP drift ends the scrape with no error anywhere.

What's exported beyond the button events:

| Metric | Why it's there |
|---|---|
| `BLE link` | Connectivity binary sensor, driven by the `ble_client` `on_connect` / `on_disconnect` triggers. ESPHome has no connection entity of its own. |
| `BLE notifications` | Monotonic count of GATT notifications, incremented before duplicate suppression — a repeat still proves the remote is transmitting. `rate()` over it answers "is the remote alive". |
| `BLE last notification age` | Seconds since the last notification; NAN until the first one ever. |
| `BLE reconnect cycles` | How often the watchdog has fired. Non-zero means the link is dropping. |
| `Battery` | The remote's own gauge. Slow-moving (30 min poll, and the gauge only re-samples at boot), so read it as a trend, not a reading. |
| `WiFi signal`, `Uptime`, `Heap free` | ESP32 health. Heap matters because `web_server` shares a single-core C3 with wifi and BLE; a downward trend precedes instability. |

**The link watchdog triggers on connection state, never on button activity.**
That distinction is the whole design. A press-timeout watchdog would have to
cycle the link on a schedule to prove liveness during the ten hours a night
nobody touches the remote, spending the coin cell to do it. Connection state is
a local bool on a mains-powered ESP32, so watching it costs the remote nothing,
and the only thing that reaches the remote — the reconnect — happens only when
the link is already down.

Mechanism: if the client has been disconnected for more than 90 s, a 30 s
`interval` forces `ble_client.disconnect` then `ble_client.connect`, then
restarts its own clock so a persistent wedge retries at the same spacing rather
than every tick. `esp32_ble_tracker`'s `auto_connect` is already retrying
underneath; the forced cycle exists to shake ESP-IDF's GATT client out of a
stuck state it will otherwise sit in indefinitely — a link that drops during a
burst of notifications has been observed staying down for hours while the ESP32
itself remained up and connected to Home Assistant the entire time.

Recovery speed has a floor we don't control: if the remote only advertises when
a button is pressed, no watchdog beats "first press wakes the link, second press
works". `BLE reconnect cycles` against the recovery timestamps is what
distinguishes that from a genuine ESP-IDF wedge.

## Changing what a button does

Home Assistant only. No reflash. The firmware knows nothing about Hue, scenes,
or any specific light — it emits `press` / `hold` / `double` on four `event`
entities and stops there.

Mappings live in `home-assistant/config/automations.yaml` as
`turn_touch_burrow_lights`. Edit and reload automations.

**`press` and `double` run the same actions.** The remote's own firmware
classifies two quick taps as a double, so anyone who presses again because the
room did not react sends `double` — the one event that would otherwise be
ignored. Binding only `press` makes a marginal link read as a completely dead
remote.

**`hold` is bound, and mirrors its own button rather than doing something
unrelated.** Each direction's hold runs a variant of that direction's own
scene — e.g. North-hold is Bright pinned to 100% brightness, South-hold turns
the fan light off (or, once it's already off, halves the room's current
brightness instead). See the `turn_touch_burrow_lights` docstring in
`automations.yaml` for the exact scene/brightness mapping per button; it
changes independently of this page.

`not_from: [unknown, unavailable]` on every trigger guards the restore
transitions that fire when the device reconnects or the integration reloads.

## Changing firmware

Over the air, from the dashboard at `bilby:6052`. USB is only needed for the
very first flash of a blank board.

Editing a device YAML in the repo does **not** reflash the device — the stack
redeploys and the dashboard picks up the new config, but the running firmware
is unchanged until someone clicks Install. Treat repo and device as capable of
diverging.

## Gotchas

- **A Hue scene named with the room prefix already baked in doubles up in
  HA.** The Hue integration always prefixes scene entity_ids with the room
  slug, so a scene created in the Hue app as e.g. "Burrow Lighter orange"
  becomes `scene.burrow_burrow_lighter_orange`, not
  `scene.burrow_lighter_orange`. Check the real entity_id via `/api/states`
  (or the frontend) before wiring a new scene into an automation — a wrong
  entity_id fails `scene.turn_on` silently, and `check_config` won't catch
  it either since it doesn't validate entity existence.
- **Events fire and forget.** If the HA API connection is down when a button is
  pressed, that event is lost, not queued. A flaky wifi link therefore presents
  as buttons that silently do nothing, with no error anywhere.
- **One API client at a time.** Running `esphome logs` holds a connection and
  can make the HA config flow fail with `connection_error`. Stop the log client
  before touching HA's integration setup.
- **The API log stream is lossy.** Log lines are dropped even when the code
  demonstrably ran. Use HA entity history as the authoritative record of what
  happened; never treat a missing log line as evidence of absence.
- **Wifi quality is only visible for devices that declare a `wifi_signal`
  sensor.** `turn-touch-burrow` does. For one that doesn't, query the UniFi
  controller for the client: signal, noise, and `tx_retries` tell the real
  story. Usable wifi wants ≥20 dB SNR.
- **A dead BLE link does not make the HA entities unavailable.** The `event`
  entities are templates on the ESP32, so they stay available as long as the
  ESP32 does — which is the whole failure mode: buttons do nothing, nothing is
  marked unavailable, and no error is logged. The `ble_client` *sensors* are the
  exception: a failed GATT read publishes NAN, so `sensor.*_battery` going
  `unknown` (not `unavailable`) is the tell that the link, rather than the
  device, is gone. `BLE link` now reports the same thing within seconds instead
  of up to half an hour later.
- ESP32-C3 is single-core, so BLE scanning contends with wifi. Scan parameters
  are deliberately low duty cycle (`interval: 1100ms`, `window: 300ms`,
  `active: false`) since only one known MAC is ever needed.
- The C3's `Serial` is the native USB-Serial/JTAG peripheral, so `hardware_uart:
  USB_SERIAL_JTAG` is required — and attaching to `/dev/ttyACM0` resets the
  chip. Prefer `esphome logs --device <ip>` over serial once it is on wifi.
