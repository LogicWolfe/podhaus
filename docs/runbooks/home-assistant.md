# Home Assistant

Home automation hub on bilby at `home.pod.haus`. Runs `network_mode: host`
and `privileged` so it can reach LAN devices directly (Hue bridge, Big Ass
Fans, Apple hubs, Bluetooth). Its config is **config-as-code** in this repo;
only runtime state stays on the host. A HomeKit bridge exposes selected
entities to Apple Home so Siri can drive them through HA.

## Topology

- **Container** `home-assistant` (`homeassistant/home-assistant:stable`) on
  bilby. `/config` is a host bind of `/var/lib/home-assistant` on local NVMe;
  `/run/dbus` is bind-mounted for Bluetooth. `extra_hosts` pins
  `music.pod.haus` to `10.0.0.119` so HA reaches Music Assistant via Caddy
  (real cert) instead of the Cloudflare AAAA (which hits Access and blocks
  server-to-server).
- **Ingress** `home.pod.haus` → bilby Cloudflare Tunnel →
  `http://172.18.0.1:8123` (`module.home_assistant` in
  `terraform/services_pod_haus.tf`), behind the `*.pod.haus` Family Access
  gate. This is the path for humans in a browser.

## Config-as-code layout

HA's `/config` mixes version-controllable YAML with state that must never be
in git. The split:

- **In the repo** — `home-assistant/config/`, bind-mounted to `/config/podhaus`
  via `${PODHAUS_REPO}/home-assistant/config:/config/podhaus:z`. (That bind
  needs `PODHAUS_REPO=[[PODHAUS_REPO]]` in `home-assistant/stack.toml`'s
  environment, or `${PODHAUS_REPO}` expands empty.)
- **On the host, never in git** — `.storage/` (auth tokens, the entity/device/
  area registries, HomeKit pairing state), the recorder DB
  (`home-assistant_v2.db`), and logs.

HA requires its root config at exactly `/config/configuration.yaml` and can't
relocate it, and single-file bind mounts are banned. So the host root is a thin
**bootstrap** that `!include`s everything real from `podhaus/`. The repo keeps
`config/configuration.root.yaml` as its **DR mirror** — the two must stay in
sync (they rarely change; see packages below).

| Repo file | Role |
|---|---|
| `config/configuration.root.yaml` | DR reference of the host bootstrap |
| `config/homeassistant.yaml` | `external_url`/`internal_url` + `packages: !include_dir_named packages` |
| `config/http.yaml` | `use_x_forwarded_for` + `trusted_proxies: 172.18.0.0/16` |
| `config/automations.yaml`, `scripts.yaml`, `scenes.yaml` | Flat `!include` targets — the UI editors write here, so they stay flat (not packages) |
| `config/packages/*.yaml` | One file per integration (drop-in) |

**Adding an integration is a drop-in.** `homeassistant.yaml` declares
`packages: !include_dir_named packages` (the path is relative to that file's
dir, so it resolves to `/config/podhaus/packages`). Drop a `<name>.yaml` in
`config/packages/`, commit, push — no edit to the host bootstrap. Each package
file is a dict of `<domain>: <config>`, e.g. `homekit.yaml` holds a top-level
`homekit:` key.

## Direct control / API

From bilby, HA's REST + WebSocket API is reachable at
`http://localhost:8123` — **local, so it bypasses Cloudflare Access** (no
server-to-server block). Auth is a long-lived token at
`op://Homelab/Home Assistant/credential`. Read state, call any service, reload
config:

```
TOK=$(op item get "Home Assistant" --vault Homelab --fields credential --reveal)
curl -s -H "Authorization: Bearer $TOK" http://localhost:8123/api/states
```

## HomeKit bridge (Siri)

`config/packages/homekit.yaml` publishes selected entities to Apple Home so
Siri controls them **through HA** (Siri → Apple Home → bridge → HA → device).
HA stays the controller.

**The bridge is export-only.** It has no import path, so it will never surface
an Apple Home accessory in HA — a HomeKit-native device (e.g. a smart lock)
stays invisible here no matter how the bridge is configured. Pulling one *into*
HA needs a different integration, and the choice matters:

- **`homekit_controller`** pairs HA to the accessory directly. A HomeKit
  accessory holds **one pairing at a time**, so this means unpairing it from
  Apple Home and losing Siri, Home app, Home Key and Apple automations.
- **Matter** is multi-admin, so Apple Home and HA can hold the device at once.
  This is the only non-destructive option. `thread` is already configured here
  (border routers via the Apple TVs/HomePods), but **`matter` is not** — and
  because this HA is a plain container rather than HAOS, it would need a
  separate `matter-server` stack, not just a config entry.

## Door locks: the request-signal shim

**The five Level Lock Touch locks cannot be integrated into HA.** Two
independent reasons, either sufficient:

- **No Matter.** Level shipped the Matter-over-Thread firmware only for the
  Lock+ and later the Bolt; the original Lock and the Lock Touch were excluded,
  and the upgrade promotion closed in January 2025. The Thread radio is in the
  hardware but has no Matter firmware.
- **No range.** That leaves Bluetooth, and bilby is out of BLE range of every
  door. Apple's hubs (Apple TVs, HomePods) are the only controllers with range.
  `homekit_controller` is therefore impossible regardless of its other costs.

So HA cannot command a lock, and never will with this hardware. What it *can*
do is change an entity Apple Home is watching:

```
HA input_boolean -> HomeKit bridge -> Apple Home automation -> hub -> BLE -> lock
```

There is no direct call — HomeKit exposes no inbound API. **The state change is
the message.**

`config/packages/door_locks.yaml` defines ten `input_boolean`s, a lock and an
unlock request for each of Pantry, Living room, Grasshopper, Front door and
Burrow. They are published to Apple Home via `packages/homekit.yaml`.
`door_lock_request_reset` in `automations.yaml` returns each to `off` ten
seconds after it fires, so every request is a fresh `off -> on` edge; Apple
triggers on the edge, so a boolean left on would make the next identical
request a silent no-op.

**These are requests, not state.** HA never learns whether a lock actually
moved, so these are not modelled as lock entities — a toggle would read as lock
state and drift the instant someone turned a knob by hand.

**Why an ordinary switch works at all:** Apple treats locks as *secure*
accessories and blocks an automation or scene from unlocking a door without
authentication. The documented way around it is to have a **non-secure** device
trigger the lock. An HA-published `input_boolean` is exactly that, which is why
only one Apple automation per direction is needed rather than a two-hop chain.
**Verified working in both directions** — unlock fires without a confirmation
prompt.

**Consumers:**

- **Night mode** (living room tap button 4) raises all five `*_lock_request`
  booleans.
- **Morning unlock**, 06:00-08:00 Australia/Perth, raising the living room and
  pantry unlock requests, from either physical control:
  - living room Hue tap, button 2 or 3
  - Kitchen fan **Haiku wall control** (`light.haiku_switch`), brightness
    increased

The wall-control trigger fires only when brightness *increases*, so dimming
never unlocks. `unavailable -> on` counts as an increase: these lights go
unavailable when their power is cut at the wall, so power returning means
someone turned them on.

`light.haiku_switch`, `light.haiku_fan_2` and `light.haiku_fan_6` mirror each
other exactly, so a wall press and an HA-driven change are indistinguishable by
entity.

### The unversioned half

**The Apple Home automations are not config-as-code.** They live in Apple's
closed database — HA can neither read nor write it. Rebuilding this house from
git restores the ten booleans and leaves them inert. Someone must then recreate,
by hand in the Home app, ten automations of the form:

> When `Front door unlock request` turns On, Set Front door to Unlocked.

This is the accepted cost of the shim; there is no way to version it. Adding a
sixth lock means a new pair of booleans here **and** two more hand-built Apple
automations, or the new door silently does nothing.

Adding entities to the bridge needs a **full HA restart**, not a reload — the
accessory list is built at bridge startup.

Genuine HA-native locks mean replacing hardware with a Matter-capable model
(e.g. Level Lock Pro). Thread is a mesh and the border routers already sit near
the doors, so Matter solves the range problem BLE cannot, and multi-admin keeps
Apple Home working at the same time.

- **Exposed:** Hue **individual bulbs** (not the Hue Room/Zone group lights —
  those overlap their member bulbs and Apple Home's own rooms), the six
  Big Ass Fans and their downlights, the ten door-lock request booleans, and
  the seven Sensibo aircon controllers. `entity_config` gives each fan/light a
  room-based HomeKit name (every BAF entity is otherwise just "Haiku Fan").
  The "Haiku Switch" wall controls are excluded — their fan/light entities
  duplicate the fans; their presence sensors are for automations, not voice.
- **`advertise_ip: 10.0.0.119`** pins the bridge to bilby's LAN address so it
  advertises on `end0`, not a docker bridge interface.
- **Firewall:** the bridge listens on `tcp/21063`. No explicit firewalld rule —
  the Apple hubs are on the LAN, covered by the `public` zone's
  `10.0.0.0/24 → accept` rule, and mDNS is already open. See
  [Hosts › Firewall](/hosts.html#bilby-firewall).

**Pairing.** The setup code is **not persisted** for a packages/YAML bridge, so
it regenerates on every restart. This only matters for the *initial* pairing —
once paired, the bridge's stable MAC + keys (in `.storage`) carry it, and the
pairing survives restarts and redeploys regardless of the changing code.
Retrieve the current code from the "HomeKit Pairing" persistent notification
(WebSocket `persistent_notification/get`) or the QR at
`/api/homekit/pairingqr?…` in that notification.

**Apple Home rooms are Apple-side only.** Room assignment lives in Apple's
closed HomeKit database — HA can neither read nor write it (no API in either
direction). HA areas and Apple Home rooms are independent; Siri room commands
("turn on the kitchen lights") resolve against Apple Home rooms, so accessories
must be placed into rooms in the Home app.

## Hue tap switches: split ownership

The four Hue Tap switches (Burrow, Bathroom, Living room, Studio) are **not**
bound in HA. Each is driven by **rules stored on the Hue bridge itself**
(`10.0.0.37`, the v1 API's `rules` collection), written by the Hue app when the
tap was paired to a room. They execute on the bridge over Zigbee, so they keep
working with HA down. They are **invisible in the Hue app UI** — the only way to
see them is `GET https://10.0.0.37/api/<key>/rules`, filtering for the tap's
`ZGPSwitch` sensor. Button events map `34 → 1`, `16 → 2`, `17 → 3`, `18 → 4`.

The taps are kinetic, so every button emits a bare `initial_press` — no hold, no
long-press. Four discrete actions, no dimming.

**A bridge rule can only reach Hue devices.** Where a room has non-Hue lights,
the pattern is to leave the bridge owning its own bulbs and add an HA automation
on the `event.<room>_switch_button_N` entities for everything else. Burrow is the
worked example (`automations.yaml`, `burrow_switch_extras`): the bridge drives
the bloom and both light strips; HA adds the Nanoleaf Shapes and the Big Ass Fan
downlight.

The consequence to remember when editing either half: **a button's behaviour is
defined in two places.** Changing what button 3 does to the Hue bulbs is a Hue
app / bridge-rule edit and is *not* captured in this repo; changing what it does
to the Shapes is a git edit here.

One bridge-side gotcha: the Hue app writes button 1 as a **toggle pair** — one
rule turning the group off when any light is on, a second turning it on when
none are. If you want a button to be off-only, the turn-on rule has to be
deleted, or HA and the bridge will disagree about the room's state.

## Hue bridge automation lives in four separate places

When hunting "what is changing this light", checking the rules collection is
**not** enough. The bridge stores automation across four unrelated resources,
and a search of one will cleanly report "nothing found" while another drives the
light:

| Resource | API | What it is |
|---|---|---|
| `rules` | v1 | Switch bindings, written by the Hue app on pairing |
| `schedules` | v1 | Timed one-shots and recurring commands |
| `behavior_instance` | v2 | The Hue app's "Automations" tab (wake up, go to sleep, coming home) |
| `smart_scene` | v2 | **Day cycles** — a room walking through scenes on clock and sunrise/sunset anchors |

`smart_scene` is the easiest to miss and the most likely answer when a light
"changes itself through the day". Enumerate all four before concluding a light
is driven from outside the bridge.

**Colour scenes on a mixed room apply unevenly.** A room holding both a colour
bulb and a dimmable-white bulb renders a colour scene faithfully on the colour
bulb and as a brightness-only approximation on the white one, so the two diverge
across a day cycle's timeslots.

**Don't read a low brightness as a fault.** A white bulb sitting at `bri: 1`
looks broken and is not: in this house it is the deliberate hallway nightlight
level for the kids. The complaint that leads here is almost never the level
itself but a schedule *moving* it — ask what the light should do and when,
rather than inferring intent from a value that looks wrong.

Anything genuinely outside the bridge and HA is most likely an **Apple HomeKit
automation** or Apple's **Adaptive Lighting**, both of which live in Apple's
closed database that neither system can read. Check the Home app's Automation
tab, and Adaptive Lighting per-accessory.

## Nanoleaf

Nanoleaf controllers pair with a token stored **on the controller**, so
**replacing the hardware invalidates the old token and changes the entity ID**
(it is derived from the serial, e.g. `light.shapes_4108`). Replacing a
controller means: delete the old config entry, re-pair, and fix up every
automation that referenced the old entity.

Two traps:

- **Effects live on the controller, not in the cloud or your account.** A
  replacement unit ships with only its stock set; custom and downloaded effects
  must be re-downloaded from the Nanoleaf app. HA matches effect names exactly,
  so an automation naming a missing effect fails silently. Check the entity's
  `effect_list` before writing a name into YAML — the stock effect is
  `Sunlight through trees`, *not* "Sunlight through the trees".
- **Pin the host to IPv4 with a DHCP reservation.** The integration accepts a
  raw IPv6 address, but a SLAAC address is derived from the delegated prefix and
  dies whenever the ISP rotates it.

To pair without the UI, drive the config flow over REST against
`/api/config/config_entries/flow` (handler `nanoleaf`, then `{"host": ...}`,
then an empty body to complete the `link` step). It returns
`not_allowing_new_tokens` until the controller's power button is held 5-7s.

## Deploy

Config changes ship like any stack: commit + push → the `podhaus-push-deploy`
procedure's content-hash mechanism sees the changed files in `home-assistant/`
and recreates the container. Validate first with:

```
docker exec home-assistant python -m homeassistant --script check_config -c /config
```

For fast automation iteration without a container recreate, call the
`automation.reload` service (the bind-mounted file is already live; reload
re-reads it in place).
