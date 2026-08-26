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
TCP 5551. `flic-pusher` dials that **on localhost** and POSTs each press to a
Home Assistant webhook, which re-fires it as the `flic_click` event that every
button automation triggers on.

```
Flic button ──BLE──> flicd ──localhost:5551──> flic-pusher ──HTTPS POST──> Home Assistant
                     └──────── both on pizero ────────┘        on bilby
```

| | |
|---|---|
| Daemon | `/opt/flicd/flicd`, upstream `50ButtonsEach/fliclib-linux-hci` armv6l build |
| Bridge | `/opt/flicd/flic-pusher`, from [`iot/pizero/`](../../iot/pizero/) |
| Units | `flicd.service` and `flic-pusher.service`, both from [`iot/pizero/`](../../iot/pizero/) |
| Bond database | `/var/lib/flicd/flicd.db` — **the pairings live here** |
| Listener | `0.0.0.0:5551`, unauthenticated |
| Webhook URL | `/etc/flic-pusher.env` (mode 0600, not in the checkout) |
| HA config | [`home-assistant/config/packages/flic.yaml`](../../home-assistant/config/packages/flic.yaml) |

### Why the Pi pushes instead of Home Assistant pulling

Home Assistant used to dial flicd itself, using the built-in `flic` platform.
That direction could not survive a reboot in either order, and on 2026-08-22 it
left the buttons dead for two days. The platform is set up exactly once: it
catches only `ConnectionRefusedError`, never raises `PlatformNotReady`, and runs
its event loop on a bare thread that returns silently when the socket drops.
So a Pi that was not up yet, a `systemctl restart flicd`, or a long enough wifi
blip all ended the same way — permanently deaf, with no log line, until someone
restarted the whole of Home Assistant.

Pushing deletes the cross-host connection rather than teaching it to reconnect.
`flic-pusher` talks to flicd over loopback where systemd supervises it, and each
press is an independent stateless POST. **Either host can now reboot whenever it
likes, in any order, with no manual step and nothing to restart.** There is
deliberately no retry logic in the pusher: losing flicd means exiting non-zero
so systemd starts a fresh process against a fresh flicd.

Two consequences worth knowing:

- **There are no `binary_sensor.flic_*` entities any more.** Nothing used them.
  Every automation triggers on the `flic_click` event, because the old
  integration initialised each binary_sensor to `on` at startup and a state
  trigger would have fired on every restart.
- **A press while Home Assistant is down is discarded, not replayed.** The POST
  fails, `flic-pusher` logs `POST failed, press dropped`, and carries on. This
  matches what the old `timeout: 3` did and is what you want: a button press has
  no meaning an hour later.

Full incident:
[`../postmortems/2026-08-22-flic-bridge-boot-order-deafness.md`](../postmortems/2026-08-22-flic-bridge-boot-order-deafness.md).

Install or reinstall with
[`iot/pizero/flicd-install`](../../iot/pizero/flicd-install) — idempotent,
and the path back after a re-flash. The Pi is an appliance rather than a
fleet host, so this is the `kangaroo_bootstrap` pattern: a committed
script for a host Ansible does not reach.

**5551 is open to the LAN.** flicd's protocol has no authentication or
encryption, so anyone on the network can enumerate buttons and watch presses.
Accepted on purpose — a firewall here buys very little and eventually costs an
evening's debugging.

Since 2026-08-24 nothing off-box connects to it: `flic-pusher` runs on this
same Pi and both bundled clients dial `localhost`. Binding
`--server-addr 127.0.0.1` in `flicd.service` would therefore close the LAN
exposure at no functional cost. Not done yet; it is a deliberate decision
waiting to be made rather than an oversight.

### The buttons

| Button | Address | Single press | Hold |
|---|---|---|---|
| Blue | `80:e4:da:73:d6:bd` | toggle the grasshopper lamp | next lamp colour |
| Green | `80:e4:da:73:e3:2b` | toggle the bookshelf lamp | next lamp colour |
| Black | `80:e4:da:73:e3:32` | toggle the LED strip | start crazy mode |

Three buttons cover four jobs, which is why black is the one whose gestures
drive unrelated things — its short press is the strip, its hold is the
whole-room light show. Crazy mode has no cancel: it runs 30 seconds and ends
itself, so the hold only ever means "start" and the button is safe to hammer.

**Crazy mode is under a 06:45–19:30 curfew**, enforced on the button. Outside
those hours the hold does nothing; everything else in the room, including
black's short press, works all night. If the show needs testing after hours,
turn on `input_boolean.grasshopper_crazy_active` from a dashboard — the
curfew is on the button, not on the flag.

The grasshopper lamp is a Nanoleaf owned by Apple Home, so blue does not
command it: it raises a request boolean that an Apple Shortcut on the HomePod
acts on. That lamp's palette lives in the Shortcut and is not in this repo.
See [`../plans/grasshopper-buttons.md`](../plans/grasshopper-buttons.md).

Bindings are automations in `home-assistant/config/automations.yaml`,
triggered on the `flic_click` event and matched by `button_address`. Trigger
on the event and match `button_address`. There is no per-button entity to
trigger on — and there was never a good one: the old integration initialised
every `binary_sensor` to `on` at startup, so a state trigger fired on every
Home Assistant restart and reload.

Nothing anywhere names these buttons. flicd knows them only as addresses and
the event carries only the address, so **this table is the sole record of which
colour is which.** Re-derive it by running `test_client.py` and pressing each
button in turn.

Each button reports **single** and **hold**, giving eight actions. Double
click is deliberately off: `flic-pusher` registers the
`on_button_click_or_hold` callback, and the alternatives that report a double
click would make every single press wait out the disambiguation window before
firing — very noticeable on a button that switches a light.

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

**A newly paired button starts working immediately.** `flic-pusher` listens
for flicd's new-verified-button event and opens a connection channel there and
then, so pairing is still the whole procedure — nothing to restart on either
host.

Continuous discovery is deliberately not run. It would let you pair by holding
a button for seven seconds with no SSH at all, but radio time on a single-core
ARMv6 board is not free while it is also holding connections to every paired
button.

### Unpairing a button

Leaving a dead button paired is not free: flicd keeps trying to reconnect
it forever, on the one core the section above exists to protect.

`fliclib.delete_button(bd_addr)` takes a single address, so it cannot
touch the other pairings. Back the bond database up first anyway — it is
the only copy, and nothing else backs it up:

```
sudo cp -n /var/lib/flicd/flicd.db /var/lib/flicd/flicd.db.bak-$(date +%Y%m%d)
```

Then from `/opt/flicd`, connect with `fliclib.FlicClient("localhost")`,
call `get_info` to confirm which addresses are verified, call
`delete_button` on the one you want, and wait for the `EvtButtonDeleted`
event before re-reading `get_info` to confirm. flicd applies it live; no
restart.

**Nothing is left behind in Home Assistant.** Since the bridge stopped
creating entities there is no orphaned `binary_sensor.flic_<addr>` to clean up;
a deleted button simply stops posting. Remove the automations bound to its
address in `home-assistant/config/automations.yaml` if it is gone for good —
otherwise they sit there matching an address that will never arrive again.

`flic-pusher` needs no action either way — flicd applies the delete live and
stops delivering that button's events. Restart the unit if you want its startup
log to list only the buttons that still exist.

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
sudo journalctl -u flicd -f               # radio + bonds
sudo journalctl -u flic-pusher -f         # presses leaving for Home Assistant
cd /opt/flicd && python3 test_client.py   # watch events without either
cd /opt/flicd && python3 test_scanner.py  # watch raw advertisements
```

The unit runs flicd as root, unsandboxed, deliberately — this is a
single-job appliance and easy debugging beats a tight blast radius.

**Work the chain in order — each step clears one half.** flicd accepts
concurrent clients, so `test_client.py` can run alongside the live bridge
without disturbing it.

1. `journalctl -u flic-pusher -b` should show `connected to flicd` and one
   `listening to <addr>` per button. If it doesn't, the problem is on this Pi.
2. Press a button. A working press logs nothing on success — silence here plus
   a healthy `test_client.py` means the press reached flicd but not the pusher.
3. `POST failed, press dropped` means the BLE half is fine and Home Assistant
   is unreachable or the webhook id is wrong. Check `/etc/flic-pusher.env`
   against `flic_webhook_id` in `/var/lib/home-assistant/secrets.yaml` on bilby.
4. If presses arrive but nothing happens in the house, the bridge is fine and
   the fault is in the automations — check
   `automation.flic_bridge_button_presses_onto_the_event_bus` last triggered.

You can exercise everything from step 3 down without touching a button, using a
made-up address so no automation matches:

```
. /etc/flic-pusher.env && curl -X POST -H 'Content-Type: application/json' \
  -d '{"button_name":"flic_test","button_address":"00:00:00:00:00:00",
       "click_type":"single","queued_time":0}' "$HA_WEBHOOK_URL"
```

**Losing `/var/lib/flicd/flicd.db` un-pairs every button.** It is the
only state on this device that is not reproducible from the repo, and
nothing backs it up on a schedule. Re-pairing is the recovery.

There are manual `flicd.db.bak-<date>` copies beside it, dropped by hand
before destructive edits. Do not mistake them for a backup: they are as
old as whenever someone last remembered, and they live on the same card
as the original, so the failure that loses one loses both.

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

- Log shipping not yet wired. Docker is unavailable on ARMv6, so this
  will be journald forwarding rather than an Alloy container. flicd logs
  to journald already, so there is something to ship.
- No backup of `/var/lib/flicd/flicd.db`, so a card failure means
  re-pairing every button.
- Nothing alerts when the bridge stops. Deliberate for now — there is no longer
  a connection that can go stale, so the remaining failure is a Pi that is
  simply off. A heartbeat POST carrying flicd's per-button connection status
  would close it if that changes.
- **Logs do not survive a reboot, by design.** Raspberry Pi OS ships
  `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf` with
  `Storage=volatile` to spare the SD card, so `journalctl -b -1` is empty and
  `--list-boots` shows only the current boot. `/var/log/journal` exists and is
  correctly owned, which makes this look broken when it is not. Don't go
  looking for history that isn't kept.
- The LED strip it was originally paired with now lives on its own
  ESP32 — see
  [`docs/runbooks/led-strip-grasshopper.md`](led-strip-grasshopper.md).
