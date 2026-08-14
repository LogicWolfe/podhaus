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

**`hci0` shows `DOWN` to `hciconfig`, and that is correct.** flicd holds
the adapter exclusively through `HCI_CHANNEL_USER`, which bypasses the
kernel's BlueZ stack entirely — so BlueZ's view of the adapter is
necessarily dead while flicd is working. `bluetooth.service` is disabled
and inactive by design. Do not "fix" this; starting bluetoothd takes the
radio away from flicd.

**mDNS does not resolve from fractal or from containers.** WSL2 has its
own network namespace with no mDNS resolver, and Docker's embedded
resolver has never done mDNS. `pizero.local` works from the LAN and from
a Mac; from anywhere else use the reserved address.

## Flic buttons

The Pi's one job. flicd owns the BLE link and serves its own protocol on
TCP 5551; Home Assistant's `flic` integration dials it and turns presses
into `flic_click` events with a `click_type` of `single`, `double` or
`hold`. No custom code sits between them.

```
Flic button ──BLE──> flicd on pizero ──TCP 5551──> Home Assistant on bilby
```

| | |
|---|---|
| Daemon | `/opt/flicd/flicd`, upstream `50ButtonsEach/fliclib-linux-hci` armv6l build |
| Unit | `flicd.service`, from [`iot/pizero/`](../../iot/pizero/) |
| Bond database | `/var/lib/flicd/flicd.db` — **the pairings live here** |
| Listener | `0.0.0.0:5551`, unauthenticated |
| HA config | [`home-assistant/config/packages/flic.yaml`](../../home-assistant/config/packages/flic.yaml) |

Install or reinstall with
[`iot/pizero/flicd-install`](../../iot/pizero/flicd-install) — idempotent,
and the path back after a re-flash. The Pi is an appliance rather than a
fleet host, so this is the `kangaroo_bootstrap` pattern: a committed
script for a host Ansible does not reach.

**5551 is deliberately open to the LAN.** flicd's protocol has no
authentication or encryption, so anyone on the network can enumerate
buttons and watch presses. Accepted on purpose — a firewall here buys
very little and eventually costs an evening's debugging.

### The buttons

| Button | Address |
|---|---|
| Blue | `80:e4:da:73:d6:bd` |
| Green | `80:e4:da:73:e3:2b` |
| White | `80:e4:da:73:c4:f1` |
| Black | `80:e4:da:73:e3:32` |

flicd knows them only as addresses and HA names its entities after them
(`binary_sensor.flic_80e4da73d6bd`), so this table is the only record of
which is which. Re-derive it by running `test_client.py` and pressing each
button in turn.

### Pairing a button

Pairing is explicit, one button at a time, and needs you holding the
button:

```
ssh nathan@pizero.local 'cd /opt/flicd && python3 new_scan_wizard.py'
```

Press and hold. A button still in private mode prints *"hold it down for
7 seconds to make it public"* — keep holding through that. Success prints
the bd_addr and exits.

Use `new_scan_wizard.py`, not `scan_wizard.py`: it drives flicd's
server-side wizard, which handles Flic 1 and Flic 2 and retries on its
own. The older script hand-rolls the same loop.

HA's own `discovery` option would let you pair by holding a button for
seven seconds with no SSH at all, but it is off — it makes HA scan
continuously, and radio time on a single-core ARMv6 board is not free
while it is also holding connections to every paired button.

### "Running" does not mean it can hear anything

flicd's TCP listener and its Bluetooth adapter come up independently, and
it will happily serve clients with no radio at all. **`systemctl is-active`
proves nothing.** The log line that matters is:

```
Successfully bound HCI socket
```

followed by `Initialization of Bluetooth controller done!`. If you only
see `Flic server is now up and running!`, flicd is deaf — it will accept
connections, accept a scan request, and never read it. The tell is a
client socket whose Recv-Q never drains:

```
ss -tn | grep 5551      # Recv-Q stuck non-zero = flicd is not listening to you
```

The cause is stopping `bluetooth.service`, which leaves the radio
rfkill-blocked for a moment. flicd binding into that window comes up deaf
and stays that way. `flicd-install` sleeps through the window and then
asserts on the HCI line rather than trusting the service state.

**Do not add `--wait-for-hci`.** It tells flicd to carry on when it cannot
bind the adapter, which converts a loud startup failure into a silently
deaf daemon. Without it flicd exits, `Restart=always` retries every five
seconds, and the journal says why.

### Debugging

```
sudo journalctl -u flicd -f               # daemon log
cd /opt/flicd && python3 test_client.py   # watch events without HA
cd /opt/flicd && python3 test_scanner.py  # watch raw advertisements
```

The unit runs flicd as root, unsandboxed, deliberately — this is a
single-job appliance and easy debugging beats a tight blast radius.

`test_client.py` is the tool for splitting "the button works" from "HA
sees it". Both bundled clients connect to `localhost`.

**Losing `/var/lib/flicd/flicd.db` un-pairs every button.** It is the
only state on this device that is not reproducible from the repo, and
nothing backs it up. Re-pairing is the recovery.

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

- DHCP reservation written (`terraform/unifi.tf`, `10.0.0.77`) but **not
  yet applied**. It needs importing first — the client already exists as
  a lease: `terraform import unifi_client.pizero b8:27:eb:68:65:04`.
  Until it lands, HA's flic config is pointed at an unreserved address.
- Log shipping not yet wired. Docker is unavailable on ARMv6, so this
  will be journald forwarding rather than an Alloy container. flicd logs
  to journald already, so there is something to ship.
- No backup of `/var/lib/flicd/flicd.db`, so a card failure means
  re-pairing every button.
- The LED strip it was originally paired with now lives on its own
  ESP32 — see
  [`docs/plans/led-strip-grasshopper.md`](../plans/led-strip-grasshopper.md).
