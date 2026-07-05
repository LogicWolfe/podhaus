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

- **Exposed:** Hue **individual bulbs** (not the Hue Room/Zone group lights —
  those overlap their member bulbs and Apple Home's own rooms), plus the six
  Big Ass Fans and their downlights. `entity_config` gives each fan/light a
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
