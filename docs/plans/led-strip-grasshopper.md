# Grasshopper LED strip — hardware assembly

Build guide for the switched USB LED strip in grasshopper. Delete this page
once the hardware is built and the ESPHome device is on the network; the
finished state belongs in [`docs/runbooks/ble-remotes.md`](../runbooks/ble-remotes.md)
alongside the other `iot/esphome/` devices.

## Status — where this is up to

Soldering is **done**: both control wires are on the module pins and on
the XIAO's D2 (red) and GND (black) keyhole pads.

Next step is the **first flash**, over USB from a Mac the board is
plugged into. See [Part E](#part-e--firmware) — the config exists in this
repo but has never been compiled, and the ESPHome dashboard has not been
redeployed, so create the device in the dashboard UI and land the repo
copy afterwards.

**The LED strip is not physically accessible right now.** The `IN`/`OUT`
column check in Part F cannot be completed until it is; everything up to
"the entity appears and toggles" can.

## What we're building

```
Home Assistant ──wifi──> XIAO ESP32C3 ──GPIO4──> F5305S module ──> USB socket ──> LED strip
                                                 (high-side switch)
```

A self-contained smart light. The ESP32 does one job — switch the strip —
and the Pi Zero does one job — bridge Flic buttons into Home Assistant.
Button-to-light is an HA automation between the two, which matches every
other remote in `iot/esphome/`.

This was originally wired to the Pi's GPIO18. That gave the Pi two jobs
and coupled the light's availability to a BLE daemon on a single-core
ARMv6 board. The ESP32 costs a few dollars and removes the coupling.

The ESP switches a **USB socket**, not the strip directly, so the strip
stays an unmodified plug-in device and the port is reusable.

## Hardware

| Item | Notes |
|---|---|
| Seeed XIAO ESP32C3 | Bare keyhole pads (through-hole + edge castellation) — no header fitted. **u.FL external antenna required** |
| F5305S MOSFET module | P-channel **high-side** switch, EL817 opto-isolated, 3–20V trigger, 5–36V load |
| USB-A extension cable | **Both** halves used — female to the strip, male to the strip's charger |
| Hookup wire | 2 lengths for the control pair |

### The antenna is not optional

The XIAO ESP32C3 has **no PCB antenna**. Wifi runs entirely through the
u.FL connector and the small external antenna in the bag. Without it the
board associates weakly at a metre and not at all across a room — which
presents as bad credentials or a bad flash, and will cost an evening.

Clip it on before flashing. The connector is fragile: press straight
down until it clicks, and never pull the cable to remove it.

## Power — two supplies, deliberately

The strip draws **5.9W ≈ 1.2A**, measured on a USB power bank. That is
far more than an ESP32 can pass through, and the XIAO's 5V pad is not a
power output of any consequence.

So the strip gets its own charger and the ESP gets its own USB cable:

- Cut the USB extension in half. The **female** half already goes to the
  module's `OUT` terminals and accepts the strip.
- The **male** half goes to the module's `IN` terminals and plugs into a
  5V charger.
- The ESP is powered by an ordinary USB-C cable into its own port.

This is electrically better than sharing, not a compromise. The EL817
optocoupler means the two sides share no ground, so with separate
supplies the isolation is genuinely doing something and the inrush
concern that a shared rail would have created disappears. A Y-splitter
can consolidate the two plugs later with no wiring change.

## Scope of soldering

The module control pins are already done. What remains:

| Joints | Where |
|---|---|
| 2 | Existing control wires onto the XIAO's **D2** and **GND** pads |
| 0 | Screw terminals — bare wire, no solder |

## Tools

- Temperature-controlled iron, fine conical tip, **320–350°C**
- 0.7–1.0mm solder — leaded 60/40 is markedly more forgiving
- Wire cutters and strippers
- Blu-tack or cardboard as a work holder
- Isopropyl alcohol + old toothbrush
- Heat-shrink tubing
- Hot glue or strong tape for strain relief
- Safety glasses; ventilation

---

## Part A — Finding the pads

**The XIAO's silkscreen labels are not GPIO numbers.** `D0`–`D10` are
board-relative names. The two that matter:

| Silkscreen | GPIO | Why this one |
|---|---|---|
| `D2` | **GPIO4** | Not a strapping pin, not UART |
| `GND` | — | Adjacent to the USB-C end |

**Do not use D0, D8 or D9.** Those are GPIO2, GPIO8 and GPIO9 — the C3's
strapping pins. A pull-down on one at power-up puts the chip into
download mode instead of running firmware, and the symptom is a board
that flashes fine and then appears dead, only when the module happens to
be connected.

GPIO20/21 are UART0. GPIO4 is free of both roles.

Orient by the **USB-C connector**, which is at one end, and count pads
from there. Check the silkscreen with a magnifier before heating
anything — the labels are tiny.

## Part B — Soldering to the pads

The XIAO's pads are **keyhole**: a full plated through-hole with a
castellation notch cut into it at the board edge. So the wire threads
through like an ordinary through-hole joint, and is mechanically captured
rather than held by solder alone.

**Use less solder than a closed hole would take.** One wall of the barrel
is missing, so surplus escapes into the notch and runs down the board
edge — and if it runs sideways it reaches the neighbouring pad. Feed a
little, stop, look.

1. Slip **heat-shrink over each wire before soldering** — it cannot go on
   afterwards.
2. If using stranded wire, tin the end so it feeds cleanly.
3. Feed the wire from the top so 2–3mm protrudes underneath.
4. Heat pad and wire together for about a second, feed solder **into the
   joint** rather than onto the tip, withdraw solder, then iron.
5. **Snip the tail flush.** A leftover stub near an adjacent pad is a
   bridge waiting to happen.
6. **Pull test.** A firm tug should not move it. A joint that looks fine
   and pulls off never wetted the pad — reheat and add a touch more solder.
7. Slide the heat-shrink over the finished joint and shrink it.

Do not expect a textbook shiny volcano; the open side prevents it. A
fillet that clearly wets both the wire and the plating is the goal.

**GND takes noticeably longer to heat** than D2 — it ties into the
board's ground pour, which sinks heat fast. Give it three or four seconds
before judging it. Solder balling up rather than flowing there is the
pour winning, not bad technique. A small amount of solder on the tip
first, as a *thermal bridge* before feeding the real solder, is the fix.

### Inspect

The pads sit **2.54mm apart**. Check under good light for a bridge
between D2 and its neighbours before first power.

Clean flux residue with isopropyl and let it dry fully.

### Strain relief — not optional

Anchor both wires to the board with hot glue or tape about a centimetre
back from the joints. The through-hole carries the load better than a
pure castellated joint would, but a repeatedly flexed pad still lifts off
the board, and a torn pad is not repairable.

## Part C — USB cable

No soldering.

1. Cut the extension in half. Keep **both** halves this time — female for
   the strip, male for the charger.
2. Strip ~40mm of outer jacket from each cut end. Score lightly and flex
   it off — the inner wires are thin (often 28AWG) and nicking them is the
   common mistake.
3. Keep **red** (+5V) and **black** (GND). Cut **white**, **green**, and
   any foil/drain wire flush and insulate them. Electrical tape wrapped
   over the cut ends is sufficient — they carry no current and only need
   to not touch anything.
4. Strip 6–7mm from red and black; twist the strands tight.
5. **Do not tin these ends.** Solder cold-flows under a screw terminal's
   clamping pressure, so a tinned end works loose over months and
   produces an intermittent fault that looks like a software bug.

## Part D — Assembly

### Module terminal map

**Polarity by row, direction by column.** Confirmed against the board's
rear silkscreen: `+` marked at both ends of one row, `−` at both ends of
the other, and a flow arrow pointing input → output.

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

### Connections

| From | To |
|---|---|
| XIAO **D2** (GPIO4) | module header `+` |
| XIAO **GND** | module header `−` |
| USB **male** half, red | `IN+` screw |
| USB **male** half, black | `IN−` screw |
| USB **female** socket, red | `OUT+` screw |
| USB **female** socket, black | `OUT−` screw |

### The one rule that matters

**Never put two wires into the same row.** The two `−` terminals are
internally bonded — that is how a high-side switch works — so bridging
them with a supply is a dead short. Supply on the left column, load on
the right.

After tightening, **tug each wire** and check for stray strands bridging
to a neighbouring terminal. A strand from `OUT+` to `OUT−` is a dead
short the moment the MOSFET turns on.

---

## Part E — Firmware

Config is at
[`iot/esphome/config/led-strip-grasshopper.yaml`](../../iot/esphome/config/led-strip-grasshopper.yaml).
It follows the house pattern: `board: seeed_xiao_esp32c3`, esp-idf
framework, encrypted API, `prometheus:` for the Alloy scrape, diagnostic
entities.

The light is `platform: binary`, not `monochromatic` — the strip does not
dim, and PWM through an optocoupler into a P-channel gate would be poor
anyway. `restore_mode: RESTORE_DEFAULT_OFF` so a power cut leaves it off.

**First flash is over USB**, because there is nothing to OTA to yet.
Everything after that is OTA from the ESPHome dashboard.

**Trap:** the esphome container's `/config` is a **volume seeded at
deploy**, not a bind mount. Compiling straight after a repo edit silently
builds the previously-deployed YAML while reporting success. Deploy the
stack first, then compile. This bit the Turn Touch work — see
[`docs/postmortems/2026-08-09-turn-touch-ble-link-wedge.md`](../postmortems/2026-08-09-turn-touch-ble-link-wedge.md).

## Part F — Verification

In order. Stop at the first surprise.

1. **Visual, unpowered.** No bridge at D2. No stray strands at the
   terminals. Correct columns. Strain relief in place. Antenna clipped on.
2. **ESP alone.** Power the ESP with nothing attached to the module;
   confirm it joins wifi and appears in Home Assistant. This separates
   "the board works" from "the circuit works".
3. **Idle.** Light off → strip **off**, module LED D1 dark.
4. **On.** Toggle the light on → D1 lights and the strip comes on.
5. **Off.** Toggle off → both go out.

### If it misbehaves

| Symptom | Cause | Fix |
|---|---|---|
| Strip permanently on, toggling does nothing | Supply and load columns swapped; current passes through the MOSFET body diode | Swap the left and right column pairs |
| Nothing lights | Red/black reversed, or the cable ignores colour convention | Swap red and black at the output terminals |
| D1 lights, strip doesn't | Output wiring or the strip | Check `OUT+`/`OUT−`, test the strip in a normal USB port |
| Board never joins wifi | Antenna not fitted | Clip the u.FL antenna on |
| Board flashes fine then appears dead, only when the module is attached | Control wire on a strapping pin | Move it to D2 |

## Open items

- [ ] Confirm the strip is plain single-colour, not addressable — a
      MOSFET switch is useless for WS2812-style strips, which need a data
      signal instead
- [ ] Solder the two control wires to D2 and GND
- [ ] Flash over USB, then verify OTA works
- [ ] UniFi DHCP reservation in `terraform/unifi.tf` — without it the
      Alloy scrape target drifts and dies silently
- [ ] Alloy scrape target in `logging/bilby/alloy-conf/config.alloy`
      alongside the Turn Touch entry
- [ ] HA automation binding a Flic press to the light
- [x] Strip current measured: 5.9W ≈ 1.2A. Own charger, not shared.
- [x] Verify the terminal map — resolved from the rear silkscreen; rows
      are polarity, the arrow is direction
