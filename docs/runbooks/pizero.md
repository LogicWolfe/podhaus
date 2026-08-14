# pizero

Raspberry Pi Zero W bridging Flic buttons into Home Assistant. An IoT
appliance, not a fleet host: no Ansible, no Komodo Periphery, no Docker.
ARMv6 rules containers out — Periphery has no armv6 image and Docker
Engine dropped the architecture — so everything on it is native systemd.

**It has one job.** No GPIO hardware is attached. The LED strip it was
originally going to switch lives on its own XIAO ESP32C3
(`iot/esphome/config/led-strip-grasshopper.yaml`), so button-to-light is
an HA automation between two single-purpose devices rather than a Pi
running a BLE daemon and a light driver on one ARMv6 core.

## Access

```
ssh nathan@pizero.local
```

Key-only. Three keys are authorised: `fractal`, `bilby`, and Nathan's
personal key. `passwordauthentication no` is set in sshd, and the account
carries `lock_passwd: true` — `passwd -S nathan` reports `L`, meaning no
password exists on the box at all. Passwordless sudo works.

## Hardware

| | |
|---|---|
| Board | Raspberry Pi Zero W **Rev 1.1** — ARMv6 (BCM2835), 512MB, BLE 4.1 |
| OS | Raspbian 13 (Trixie), kernel `6.18.34+rpt-rpi-v6` |
| Wifi MAC | `b8:27:eb:68:65:04` — 2.4GHz only |
| BT adapter | `hci0`, `B8:27:EB:97:9A:FB`, UART bus |

The **`-v6` kernel suffix is load-bearing**: it is the ARMv6 build. Only
the 32-bit armhf image boots this board. A 64-bit arm64 image will not
run on ARMv6 and hangs with a steady ACT LED — and the Zero has no
separate power LED, so a board that never boots looks identical to one
with no power.

Hardware obsolescence for the 32-bit boards begins from January 2026, so
this device has a finite support runway. Fine for an appliance; not
somewhere to invest heavily.

## Provisioning — cloud-init, not `custom.toml`

**This is the thing to know before touching the card.**

Raspberry Pi OS Trixie provisions with **cloud-init**. The older
`custom.toml` mechanism — read by `raspberrypi-sys-mods`' `firstboot` and
`init_config` — **does not exist in this image**. The string `custom.toml`
appears nowhere in its root filesystem. Writing one has no effect
whatsoever: no account is created, `userconfig.service` sits on tty8
waiting for someone to type a username, and that blocks `multi-user.target`
and with it all networking.

The failure presents as a Pi that boots but never appears on the network,
which is indistinguishable from bad wifi credentials unless you know to
look for this.

`raspberrypi-sys-mods` on GitHub still carries the `custom.toml` parser on
master. **Its presence upstream is not evidence it is in the image** —
that mistake is what produced the failure above.

### The four files on the boot partition

Written to the FAT partition root (`/boot/firmware` once running):

| File | Purpose |
|---|---|
| `user-data` | cloud-config: user, three SSH keys, hostname, timezone, `bootcmd` |
| `meta-data` | instance-id — **bump it to force cloud-init to re-run** |
| `network-config` | netplan v2 `wifis`: SSID + PSK |
| `ssh` | empty marker file — without it sshd never starts |

The datasource resolves as
`DataSourceNoCloud [seed=ds_config_seedfrom,file:///boot/firmware]`.

### `ssh.service` is not enabled by default

Only **`sshswitch.service`** is. It enables SSH solely when an empty file
named `ssh` exists on the boot partition. Omit it and the Pi joins wifi
happily while refusing port 22 — a symptom that reads like a firewall or
network fault and is neither.

The marker is **consumed on first boot**: sshswitch enables `ssh.service`
permanently and removes the file, so it is absent from a running system.
Both units now report `enabled`. Do not read its absence as a problem.

### Wifi country goes in `bootcmd`, not `runcmd`

The radio is rfkill-blocked until a regulatory domain is set. `runcmd`
executes *after* the point where networking needs the radio, so setting
the country there is too late. `bootcmd` runs early enough.

## Expected states that are not faults

**`cloud-init status --long` reports `degraded done`.** `errors: []`. The
sole recoverable warning is a missing `cc_netplan_nm_patch` module — an
upstream packaging bug dated to the image's own build. Nothing to fix.

**Avahi may rename itself `pizero-2.local`** after a fast reboot, if the
previous `pizero.local` record has not aged out. The Linux hostname stays
correct; only mDNS is affected. Reclaim it with:

```
sudo systemctl restart avahi-daemon
```

**`hci0` shows `DOWN`** with `bluetoothd` logging `Failed to set mode:
Failed (0x03)`. Not worth chasing — flicd claims the radio exclusively
through `HCI_CHANNEL_USER` and requires BlueZ out of the way, so
`bluetooth.service` gets disabled regardless. What matters is that the
adapter enumerates, and it does.

## GPIO

**sysfs GPIO (`/sys/class/gpio`) is gone on Trixie.** Anything written
against that interface will not work. Use libgpiod or gpiozero.

Available: `/dev/gpiochip0` and `/dev/gpiochip4`, with `gpioget`,
`gpioset` and `pinctrl` installed, and `gpiozero` importable.

**Nothing is wired to the GPIO holes**, which are bare — no header is
fitted. Keep it that way: this board's remaining job is BLE, and a
second load on a single ARMv6 core is what the ESP32 exists to avoid.

## Power

`vcgencmd get_throttled` reads **`0x0`** — no undervoltage, current or
historical. Bit 0 is undervoltage now; bit 16 is undervoltage since boot.

A non-zero result here means the supply or cable can't carry the board.
Voltage drop across a thin micro-USB cable is the usual cause, and the
failure mode is an intermittent reset or SD corruption that will look
like a software bug.

## Re-flashing

1. Write the **32-bit armhf** image
   (`https://downloads.raspberrypi.com/raspios_lite_armhf_latest`) to the
   **whole disk**, not a partition node.
2. Verify `kernel.img` exists on the boot partition before going further.
   Only `kernel8.img` means a 64-bit image was written.
3. Place `user-data`, `meta-data`, `network-config` and `ssh` at the
   partition root. **Do not write `custom.toml`** — it does nothing.
4. Eject cleanly before removing the card.

To re-run cloud-init on an existing card, bump the instance-id in
`meta-data`.

## Open items

- No DHCP reservation yet. Currently `10.0.0.77`. Anything that addresses
  this device by IP — a metrics scrape target, a Home Assistant entry —
  needs a reservation in `terraform/unifi.tf` first, or it dies silently
  on the next DHCP drift. Same trap documented for the Turn Touch ESP32.
- Log shipping not yet wired. Docker is unavailable on ARMv6, so this
  will be journald forwarding rather than an Alloy container.
- flicd not yet installed. It claims the radio exclusively via
  `HCI_CHANNEL_USER`, so `bluetooth.service` must be disabled first.
- The LED strip it was originally paired with now lives on its own
  ESP32 — see
  [`docs/plans/led-strip-grasshopper.md`](../plans/led-strip-grasshopper.md).
