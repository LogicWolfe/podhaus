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
remote. Hold stays unbound deliberately; without a filter a hold would fire the
scene a second time.

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

- **Events fire and forget.** If the HA API connection is down when a button is
  pressed, that event is lost, not queued. A flaky wifi link therefore presents
  as buttons that silently do nothing, with no error anywhere.
- **One API client at a time.** Running `esphome logs` holds a connection and
  can make the HA config flow fail with `connection_error`. Stop the log client
  before touching HA's integration setup.
- **The API log stream is lossy.** Log lines are dropped even when the code
  demonstrably ran. Use HA entity history as the authoritative record of what
  happened; never treat a missing log line as evidence of absence.
- **Wifi quality is not visible in HA** unless the device config declares a
  `wifi_signal` sensor. To check it from outside, query the UniFi controller for
  the client: signal, noise, and `tx_retries` tell the real story. Usable wifi
  wants ≥20 dB SNR.
- ESP32-C3 is single-core, so BLE scanning contends with wifi. Scan parameters
  are deliberately low duty cycle (`interval: 1100ms`, `window: 300ms`,
  `active: false`) since only one known MAC is ever needed.
- The C3's `Serial` is the native USB-Serial/JTAG peripheral, so `hardware_uart:
  USB_SERIAL_JTAG` is required — and attaching to `/dev/ttyACM0` resets the
  chip. Prefer `esphome logs --device <ip>` over serial once it is on wifi.
