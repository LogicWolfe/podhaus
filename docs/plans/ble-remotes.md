# BLE remotes — remaining work

The burrow Turn Touch is built and working; see
[`docs/runbooks/ble-remotes.md`](../runbooks/ble-remotes.md) for how it works.
What follows is only what is left.

Paused 2026-08-08, waiting on an antenna.

## Fix the burrow ESP32's wifi (blocker)

The board reaches HA but the link is far too weak to be reliable. Measured
2026-08-08 from the UniFi controller and bilby:

```
signal -91 dBm, noise -96 dBm   →  SNR 5 dB     (usable wants ≥20)
tx_retries 1930  vs  tx_packets 793             (~244% retry rate)
tx/rx rate 26000 / 6000 kbps                    (near the 2.4 GHz floor)
ping  min/avg/max/mdev = 1.98 / 49.9 / 119.9 / 34.1 ms
associated to Hallway AP (24:5a:4c:5f:35:b0), 2.4 GHz ch 11
```

Symptom: the device drops its HA API connection every few minutes without
rebooting (uptime kept climbing across two dropouts). Because events are fire
and forget, every press during a dropout is silently lost. Two of four buttons
produced nothing at all during a four-button test.

**Chosen fix: add an external antenna to the board.** Before buying, confirm the
board can take one — many ESP32-C3 boards (the SuperMini style in particular)
have only a PCB or ceramic antenna and no connector. Look for a ~2 mm square
U.FL/IPEX socket near the RF end. The `-1U` / `-02U` variants of the C3-MINI and
C3-WROOM are the ones built for it. Some dual-option boards carry the socket but
route RF to the onboard antenna until a 0 Ω resistor is moved. Swapping in a
`-1U` module may be cheaper than modding this one; there are spare boards.

Placement is the other half and costs nothing: the ESP32 does **not** need to
sit beside the remote. BLE reaches roughly 10 m, so it can move to whichever
outlet balances BLE range against AP proximity.

Re-measure after the antenna using the same UniFi fields — signal, noise,
`tx_retries` — not "does it feel better".

## Add wifi diagnostics to the firmware

Deliberately not applied yet: editing the YAML does not reflash the device, so
committing it now would leave the repo describing firmware that isn't running.
Apply and OTA together, next time the device is being flashed anyway.

Add to `iot/esphome/config/turn-touch-burrow.yaml`:

- `wifi: power_save_mode: none` — ESPHome defaults to light power-save on ESP32,
  which costs latency and connection stability on a mains-powered device.
- a `wifi_signal` sensor and an uptime sensor, so the next diagnosis is a glance
  at HA rather than an expedition into the UniFi API.

## Second Turn Touch

A second Turn Touch exists but was not advertising during discovery, so **its
MAC is still unknown** — that is the first step. Once known it needs its own
ESP32 and its own flat device YAML in `iot/esphome/config/`, plus a matching HA
automation. Nothing in the design is shared between the two boards.

## Nuimo Control

Not started beyond discovery. Nothing is validated — the decode below is the
GATT layout only, never confirmed against live notifications.

- **MAC** `D0:6F:32:35:26:12` (advertises as `Nuimo`, seen at -67 dBm)
- **Characteristics** (base `f29b15xx-cb19-40f3-be5c-7241ecb82fd2`):
  `1529` button, `1526` fly, `1527` swipe/touch, `1528` rotation, `152b`
  unknown; battery on the standard `0x2a19`.

The rotary ring is the interesting part and the reason this is more work than
the Turn Touch: it emits a continuous stream rather than discrete edges, so it
needs a decode that accumulates and a decision about how to represent it in HA
(an `event` per detent, or a number entity tracking position).

Capture live notifications per gesture before writing any decode. The Turn
Touch work established the method: script a guided capture that prompts for one
specific physical action at a time and records raw bytes with timestamps, then
derive the decode from the captured data rather than from assumptions.

## Pico buttons

Requested 2026-08-08, scope not yet defined — capture requirements before
starting. Unknown at time of writing whether these reach HA over BLE via an
ESP32 like the others, or through some other path entirely; that determines
whether this shares the `iot/esphome/` pattern or needs its own.
