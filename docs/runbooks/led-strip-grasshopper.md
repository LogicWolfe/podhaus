# Grasshopper LED strip

A switched USB LED strip in grasshopper, exposed to Home Assistant as an
ordinary light. A XIAO ESP32C3 running ESPHome drives an opto-isolated
high-side MOSFET module, which makes and breaks the +5V rail of a USB
socket the strip plugs into.

```
Home Assistant ──wifi──> XIAO ESP32C3 ──GPIO4──> F5305S module ──> USB socket ──> LED strip
                                                 (high-side switch)
```

The ESP does one job: switch the strip. Binding a button to it is a Home
Assistant automation, the same as every device in
[`iot/esphome/`](ble-remotes.md). The strip itself is unmodified — it
plugs into a USB socket, so the port stays reusable and the strip stays a
plain consumer device.

The strip is plain single-colour, not addressable. A MOSFET that switches
the whole rail would be useless on a WS2812-style strip, which needs a
data signal instead.

## Identity

| | |
|---|---|
| Device | `led-strip-grasshopper` |
| Config | [`iot/esphome/config/led-strip-grasshopper.yaml`](../../iot/esphome/config/led-strip-grasshopper.yaml) |
| Board | Seeed XIAO ESP32C3 (`seeed_xiao_esp32c3`), ESP32-C3 QFN32 rev v0.4, 4MB flash |
| Wifi MAC | `AC:27:6E:81:E2:D8` |
| Entity | `light.grasshopper_led_strip_strip` |
| HA config entry | `Grasshopper LED Strip`, domain `esphome` |
| Control pin | `GPIO4` — silkscreen `D2` |

The board name matters: `seeed_xiao_esp32c3`, **not** `esp32-c3-devkitm-1`.
Same chip, different board definition and different pin labels. The
XIAO's silkscreen `D0`–`D10` are board-relative names, not GPIO numbers.

**Wifi runs entirely through the u.FL connector.** This board has no PCB
antenna. Without the external antenna fitted it associates weakly at a
metre and not at all across a room, which reads as bad credentials or a
bad flash. The connector is fragile — press straight down until it
clicks, and never pull the cable to remove it.

## Wiring

`D2` (GPIO4) was chosen because `GPIO2`, `GPIO8` and `GPIO9` are the C3's
strapping pins — a pull on one at power-up changes boot mode, and the
symptom is a board that flashes fine and then appears dead, but only when
the module happens to be connected. `GPIO20`/`GPIO21` are UART0. GPIO4 is
free of both roles.

The module's control input is opto-isolated (EL817) and active-HIGH:
current through the opto's LED pulls the P-channel gate down and switches
+5V through to the socket. Roughly 5mA at 3.3V through the module's 200R
series resistor.

### Module terminals

Polarity by row, direction by column.

```
   ┌──────────────────────────────────┐
   │   [2-pin header]   −   +         │
   │                                  │
   │    D1   EL817        F5305S      │
   │                                  │
 − ─┤   ┌──────────┬──────────┐       │
   │   │   IN−     │   OUT−   │       │
   │   ├───────────┼──────────┤       │
 + ─┤   │   IN+     │   OUT+   │       │
   │   └───────────┴──────────┘       │
   └──────────────────────────────────┘
          supply        load
```

| From | To |
|---|---|
| XIAO `D2` (GPIO4) | module header `+` |
| XIAO `GND` | module header `−` |
| USB male half, red | `IN+` |
| USB male half, black | `IN−` |
| USB female socket, red | `OUT+` |
| USB female socket, black | `OUT−` |

**Never put two wires into the same row.** The two `−` terminals are
internally bonded — that is how a high-side switch works — so bridging
them with a supply is a dead short. Supply on the left column, load on
the right.

## Power — two supplies, deliberately

The strip draws 5.9W ≈ 1.2A, far more than an ESP32 can pass through.
So the strip has its own 5V charger into `IN`, and the ESP has its own
USB-C cable.

This is better than sharing rather than a compromise: the optocoupler
means the two sides share no ground, so with separate supplies the
isolation is genuinely doing something, and the inrush a shared rail
would have created disappears. A Y-splitter can consolidate the two
plugs with no wiring change.

## Firmware

Follows the house pattern — esp-idf framework, encrypted API,
`prometheus:` for the Alloy scrape, diagnostic entities. The light is
`platform: binary`, not `monochromatic`: the strip does not dim, and PWM
through an optocoupler into a P-channel gate would be poor anyway.

`restore_mode: RESTORE_DEFAULT_OFF` **restores the last state across a
power cut.** It reads the saved state from flash and only falls back to
OFF when nothing has been saved yet — the first boot after a flash. If a
power cut should instead force the strip off, that is `ALWAYS_OFF` (or
`RESTORE_AND_OFF`).

Updates are OTA from the ESPHome dashboard on `bilby:6052`. A first flash
on a bare board has to be over USB, since there is nothing to OTA to:
compile in the dashboard, then write `firmware.factory.bin` to offset
`0x0` with `esptool`.

Editing the config goes through the repo, and the deploy seeds the
dashboard's config volume — see
[BLE remotes](ble-remotes.md) for that flow and its traps, which apply
identically here.

## Driving it by hand

Normally: it is an ordinary HA light, so `light.turn_on` /
`light.turn_off` on `light.grasshopper_led_strip_strip`, or the tile in the
dashboard. Adoption into HA is a config entry, not YAML — see
[adopting a device](ble-remotes.md) for how that entry is created and why it
cannot live in the repo.

The rest of this section is for driving the board directly, with HA out of the
picture — useful when diagnosing whether a fault is in the device or in HA.

`web_server:` on ESPHome 2026.7.4 serves a single-page app, and its REST
routes are not what older documentation describes: `GET /light/<id>` and
`GET /sensor/<id>` return 404, and the control routes return 411 without
a body and 404 with one.

To **read** state, use the SSE stream, which emits every entity:

```
curl -sN http://led-strip-grasshopper.local/events
```

To **control** it, use the native API — the same path Home Assistant
uses. Running it inside the esphome container lets it read the key
straight from `/config/secrets.yaml`, so the key never crosses a shell
boundary:

```
docker exec esphome python /tmp/led.py on   # or off / state
```

## If it misbehaves

| Symptom | Cause | Fix |
|---|---|---|
| Strip permanently on, toggling does nothing | Supply and load columns swapped; current passes through the MOSFET body diode | Swap the left and right column pairs |
| Nothing lights | Red/black reversed, or the cable ignores colour convention | Swap red and black at the output terminals |
| Module LED `D1` lights, strip doesn't | Output wiring or the strip | Check `OUT+`/`OUT−`, test the strip in a normal USB port |
| Board never joins wifi | Antenna not fitted | Clip the u.FL antenna on |
| Entity `unavailable` in HA, device pings fine | API key rotated in 1Password, or the address drifted | Re-add the config entry with the current key — see [adopting a device](ble-remotes.md) |
| Board flashes fine then appears dead, only when the module is attached | Control wire on a strapping pin | Move it to `D2` |

`D1` on the module is the useful diagnostic: it sits on the control side,
so `D1` lit with a dark strip isolates the fault to the output side,
and both dark points back at the control pair or `IN`.
