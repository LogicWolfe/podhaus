# Grasshopper LED strip — remaining integration

The hardware is built, flashed and working: an API call switches the
strip. How it is wired, how the firmware is configured and how to drive
or troubleshoot it now live in
[`docs/runbooks/led-strip-grasshopper.md`](../runbooks/led-strip-grasshopper.md).

What is left is integration. Delete this page once these land.

- [ ] **Verify OTA works.** Never yet exercised — the first flash was
      over USB. Until an OTA succeeds, the board is only recoverable with
      a cable, which means taking it down off the wall.
- [ ] **UniFi DHCP reservation** in `terraform/unifi.tf` for
      `AC:27:6E:81:E2:D8`. Without it the address drifts and the Alloy
      scrape target dies silently — the same failure as the Turn Touch
      device in
      [`docs/postmortems/2026-08-09-turn-touch-ble-link-wedge.md`](../postmortems/2026-08-09-turn-touch-ble-link-wedge.md).
      Do this before the scrape target, not after.
- [ ] **Alloy scrape target** in `logging/bilby/alloy-conf/config.alloy`,
      alongside the Turn Touch entry. The firmware already exposes
      `prometheus:`; nothing is collecting it.
- [ ] **Home Assistant automation** binding a Flic press to the light.
      This is the last piece that makes it useful without a phone.
