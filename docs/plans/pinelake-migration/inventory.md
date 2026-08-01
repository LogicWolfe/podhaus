# Pinelake inventory

Read-only snapshot of `home.pinelake.haus` taken 2026-05-13. Every other
doc in this plan references this one. If state on the host changes,
update this file first.

## Host

| Field | Value |
|---|---|
| Hostname | `Baxters-Mac-mini.local` (CNAME-fronted: `home.pinelake.haus`) |
| Hardware | Apple M1 Mac mini (`Macmini9,1`), 8 CPU, 16 GiB RAM, arm64 |
| OS | macOS 26.2 (build `25C56`), Darwin `25.2.0` |
| Login user | `baxter`, uid 501, gid 20 (`HOME=/Users/baxter`) |
| Uptime | 25 d 14 h (booted 2026-04-17); no idle-sleep events in 7 d of `pmset` log |
| Reachable via | Cloudflare tunnel (`home.pinelake.haus → ssh://localhost:22`), tailnet (`100.124.202.28`), LAN (`192.168.1.128`, Gigabit Ethernet) |

### Disks

| Device | Mount | Size | Notes |
|---|---|---|---|
| Internal NVMe | `/`, `/System/Volumes/Data` | 1 TB APFS, ~610 GiB free | OS + user homes + container state |
| `/dev/disk6` | `/Volumes/TerraMaster` | 14 TB APFS, 6.6 TiB used / 6.3 TiB free | Direct-attached USB enclosure (NOT iSCSI/SMB). Mounted `noowners`. |

The TerraMaster enclosure auto-mounts at boot but is **racy** — the
hand-rolled `colima-start-wait.sh` exists specifically to deal with the
case where colima starts before `/Volumes/TerraMaster` is ready.

## Container runtime

### Colima

Single profile (`default`), config at
`/Users/baxter/.colima/default/colima.yaml`.

| Field | Value |
|---|---|
| Colima version | 0.9.1 |
| Runtime | docker |
| vmType | vz (Apple Virtualization framework) |
| Arch | aarch64 |
| CPUs | **2** (undersized — see below) |
| RAM | **2 GiB** (undersized) |
| Disk | 100 GiB sparse (~292 MB used) |
| Mounts | virtiofs — `/Users/baxter` (RW) and `/Volumes/TerraMaster` (RW) |
| Kubernetes | disabled |
| Rosetta | disabled |
| Auto-activate context | yes |

VM root: `/dev/vdb1`, 98 GiB. `~/.colima` on host: 2.3 GiB total.

**Sizing decision needed**: 2 CPU / 2 GiB will not accommodate Komodo
Periphery + the migrated stacks + the existing flood container. Bilby's
periphery alone is comfortably-sized; pinelake should sit at minimum
**4 CPU / 8 GiB**, possibly **6 CPU / 12 GiB** given Plex transcoding.
Disk should grow to 200 GiB to hold container images + Plex's
`Plug-in Support/Caches` if Plex stays containerised.

### Docker

| Field | Value |
|---|---|
| Client | `/opt/homebrew/bin/docker` v29.1.4 |
| Server (in VM) | v28.4.0 |
| Active context | `colima` (`unix:///Users/baxter/.colima/default/docker.sock`) |
| Other contexts | `default` (`/var/run/docker.sock` — not usable, nothing listening) |
| `docker compose` plugin | **NOT INSTALLED** |
| `docker-compose` v1 | NOT INSTALLED |

The lack of `docker compose` is fine for Komodo (Periphery runs compose
inside its own container), but means no human can run `docker compose
up` from the shell on this host without first installing the plugin.

### Networks

Only the three Docker defaults: `bridge` (`172.17.0.0/16`), `host`,
`none`. **`dockernet` does not exist.** Has to be created as part of
the migration so the podhaus pattern (`172.18.0.0/16`, container-name
DNS) works.

### Volumes

**None.** All persistent state is on host bind mounts.

## Containers

Exactly one running container, no stopped containers worth preserving.

### `rtorrent-flood`

| Field | Value |
|---|---|
| Image | `jesec/rtorrent-flood:latest` (arm64, sha `a80e18cb3168`) |
| State | running, restart `unless-stopped` |
| Network | default `bridge` |
| Ports | `0.0.0.0:3000 → 3000/tcp` (Flood UI) |
| User | `501:<gid-of-/Users/baxter-in-VM>` (computed at runtime by the launcher script) |
| Cmd | `/sbin/tini -- flood --auth none --rtconfig /config/.rtorrent.rc --rtsocket /tmp/rtorrent.sock --allowedpath /data` |
| Env | `HOME=/config`, `FLOOD_OPTION_HOST=0.0.0.0`, `FLOOD_OPTION_RTORRENT=true` |
| Binds | `/Users/baxter/.config/torrent → /config` (308 KB), `/Volumes/TerraMaster/Torrents → /data` (1.2 TiB) |
| Compose project | **none** — launched by `/Users/baxter/.config/torrent/run_container.sh` |
| Auth | `--auth none`; relies entirely on Cloudflare Access at `torrent.pinelake.haus` |

The `run_container.sh` source-of-truth:

```sh
docker run -d --name rtorrent-flood --restart unless-stopped \
  -u "$(id -u):$(colima ssh -- stat -c %g /Users/baxter)" \
  -e HOME=/config -p 3000:3000 \
  -v /Users/baxter/.config/torrent:/config \
  -v /Volumes/TerraMaster/Torrents:/data \
  jesec/rtorrent-flood --auth none \
  --rtconfig /config/.rtorrent.rc --rtsocket /tmp/rtorrent.sock --allowedpath /data
```

`.rtorrent.rc` lives at `/Users/baxter/.config/torrent/.rtorrent.rc`
(6.1 KB). Session state under `.local/share/rtorrent/.session/`,
watch / download / log subdirs alongside.

Stale image `alpine:latest` (13.6 MB) present but unused.

## Native (non-container) services

Everything else of interest runs natively under launchd / login items.

### Plex Media Server

| Field | Value |
|---|---|
| Bundle | `/Applications/Plex Media Server.app` |
| Version | 1.40.4.8679-424562606 (arm64 native universal build) |
| Process | PID 14017 + sibling processes (`Plex Tuner Service` on 127.0.0.1:32600, `Plex EAE Service`) |
| Auto-start | Login Item (LSAgent — `application.com.plexapp.plexmediaserver.*`). No LaunchAgent plist. |
| Listening | `*:32400` (TCP, IPv4+IPv6) — bound to all interfaces |
| State dir | `/Users/baxter/Library/Application Support/Plex Media Server/` (22 GB) |
| Preferences | `/Users/baxter/Library/Preferences/com.plexapp.plexmediaserver.plist` (1.2 KB) — macOS equivalent of `Preferences.xml` |
| MachineIdentifier | `c9d75740-0fd3-4bba-9874-be61f5dc8d38` |
| ProcessedMachineIdentifier | `92311858cdd55fb33583fda2e6fc037e3655da85` |
| CertificateUUID | `5801df40ceea4deaaefd8bd027fc22ff` (v3) |
| FriendlyName | `Pine Lake` |
| PlexOnlineToken | **present** (redacted; held in plist) |
| OldestPreviousVersion | `1.27.2.5929-a806c5905` — server running continuously since 2022 |
| Backups | **none** off-host. Time Machine not configured. Plex's own scheduled DB dumps present (`Plug-in Support/Databases/com.plexapp.plugins.library.db-2026-05-{04,07,10,13}`). |

State breakdown (22 GB total):

| Subdir | Size | Notes |
|---|---|---|
| `Plug-in Support/Databases/` | 694 MB | Library DB (33 MB), blobs DB (82 MB), WAL/SHM, scheduled backups |
| `Metadata/` | 1.4 GB | Posters, art, agent payloads (Movies + TV Shows) |
| `Media/` | 20 GB | Thumbnails, BIFs, intro detection |
| `Updates/` | 291 MB | Disposable |
| `Scanners/` | 92 MB | Bundled; will be re-supplied by image |
| `Codecs/` | 6 MB | Per-host downloaded shared objects |

Library sections (from `com.plexapp.plugins.library.db`):

| ID | Name | Type | Roots |
|---|---|---|---|
| 2 | Films | movie | `/Volumes/TerraMaster/Movies`, `/Volumes/TerraMaster/Torrents/Movies` |
| 3 | TV shows | show | `/Volumes/TerraMaster/TV`, `/Volumes/TerraMaster/Kids/TV`, `/Volumes/TerraMaster/Torrents/TV` |
| 4 | Sports | movie | `/Volumes/TerraMaster/Sports`, `/Volumes/TerraMaster/Torrents/Sports` |

All sections root in `/Volumes/TerraMaster`. Library DB path rewriting
on migration is risky; preserving the path on the destination is
safer.

### Syncthing

| Field | Value |
|---|---|
| Binary | `/opt/homebrew/opt/syncthing/bin/syncthing` (Homebrew) |
| Auto-start | `~/Library/LaunchAgents/homebrew.mxcl.syncthing.plist` (user-scoped LaunchAgent, `KeepAlive`, args `-no-browser -no-restart`) |
| State dir | `/Users/baxter/Library/Application Support/Syncthing/` (345 MB; mostly `index-v0.14.0.db`) |
| GUI | `127.0.0.1:8384` (loopback only) — Cloudflare Access fronts it |
| Sync ports | `*:22000` TCP+UDP (LAN/tailnet-reachable) |
| Folders | `default` (sendreceive, `/Users/baxter/Sync`, shared with Baxters-Mini + Wombat + alligator) and `pouch` (**receiveonly**, `/Volumes/TerraMaster`, shared with Baxters-Mini + Kangaroo + alligator) |

The `alligator` peer-id is dead (alligator was retired 2026-04-14) and
should be cleaned out post-migration.

### cloudflared

| Field | Value |
|---|---|
| Binary | `/opt/homebrew/bin/cloudflared` (Homebrew, v2025.11.1; 2026.3.0 was available at the audit) |
| Auto-start | `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` (root, `RunAtLoad`, `KeepAlive`) |
| Cmd | `cloudflared --config /etc/cloudflared/config.yml tunnel run` |
| Active config | `/etc/cloudflared/config.yml` (root:wheel, 644) |
| Stale config | `/Users/baxter/.cloudflared/config.yml` — present but unused (lacks ssh rule, lacks `httpHostHeader: localhost`) |
| Credentials | `/etc/cloudflared/fec5ca76-b634-4185-bdb2-f85c38b1b570.json` (root:wheel, 600) |
| Origin cert | `~/.cloudflared/cert.pem` (baxter, used for `cloudflared tunnel list` etc) |
| Tunnel UUID | `fec5ca76-b634-4185-bdb2-f85c38b1b570` (named `torrent-pinelake`) |
| Connections | 2×SEA + 2×YYC, healthy |

Ingress rules (from `/etc/cloudflared/config.yml`):

| Hostname | Backend | Notes |
|---|---|---|
| `home.pinelake.haus` | `ssh://localhost:22` | SSH-over-Access |
| `torrent.pinelake.haus` | `http://127.0.0.1:3000` | rtorrent-flood |
| `sync.pinelake.haus` | `http://127.0.0.1:8384` | syncthing; `originRequest.httpHostHeader: localhost` |
| catch-all | `http_status:404` | required terminator |

### Tailscale

| Field | Value |
|---|---|
| Build | App Store / GUI (`/Applications/Tailscale.app`) |
| Daemon | per-user `IPNExtension` (PID 24784); **no LaunchDaemon**, no watchdog |
| CLI | **not installed** (App Store build requires opt-in via app menu) |
| Tailnet | `tailcfb5f.ts.net` |
| Addresses | `100.124.202.28/32` (v4), `fd7a:115c:a1e0:ab12:4843:cd96:627c:ca1c/48` (v6) |
| Routes | none advertised (not a subnet router, not an exit node) |
| MTU | 1280 |
| WireGuard | listening UDP `*:41641` |

### Other native processes

| Process | PID | Source |
|---|---|---|
| `Plex Tuner Service` | child of Plex | bundled, listens `127.0.0.1:32600` |
| `Plex EAE Service` | child of Plex | Easy Audio Encoder |
| `colima daemon` | 27406 | spawned by `colima start`, `--inotify` for both mount roots |
| `limactl usernet` | 27435 | colima child, subnet `192.168.5.0/24` |
| `limactl hostagent` | 27442 | colima child, VM lifecycle |

No native `caffeinate`, `rtorrent`, or anything else of note.

## Auto-start orchestration (launchd)

| Plist | Scope | What it owns |
|---|---|---|
| `/Library/LaunchDaemons/io.colima.start.plist` | system, runs as `baxter` | `/usr/local/bin/colima-start-wait.sh` at boot |
| `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` | system, root | cloudflared tunnel run |
| `~/Library/LaunchAgents/homebrew.mxcl.syncthing.plist` | user | syncthing |
| (login item) | LSUIElement | Plex Media Server.app |
| (login item) | LSUIElement | Tailscale.app |

The `colima-start-wait.sh` wrapper is operational scar tissue worth
preserving:

```sh
# /usr/local/bin/colima-start-wait.sh — paraphrased
wait_up_to 600s for /Volumes/TerraMaster/Torrents to exist
scrub orphan limactl, stale _networks/, ha.sock, in_use_by symlinks
colima start
```

The boot race it solves (TerraMaster mounts after colima would
otherwise start, leaving limactl with stale locks) **will recur** if
the periphery is wired to start independently. The Komodo Periphery
container should be `--restart unless-stopped` under Docker, which
means it gets started by the Docker daemon after colima is up, which
means it inherits the race solution for free. Don't add a separate
LaunchAgent for periphery.

## Network paths

Three independent ways to reach the host today:

| Path | Endpoint | Failure modes |
|---|---|---|
| Cloudflare tunnel | `*.pinelake.haus` (CF anycast → tunnel) | cloudflared crash, CF outage, ISP outage |
| Tailnet | `100.124.202.28` or `pinelake.<tailnet>.ts.net` (MagicDNS) | IPNExtension crash (no watchdog), Tailscale DERP outage, ISP outage |
| LAN | `192.168.1.128:<port>` | router reboot, NIC failure |

Cloudflare and Tailscale are independent control planes — Tailscale is
a viable fallback when Cloudflare is degraded. The only shared
failure mode is ISP egress; nothing cheap (within reason) fixes that
for a home network with one WAN.

Plex (`*:32400`), Syncthing data port (`*:22000`), AirPlay
(`*:5000`,`*:7000`) all bind to `0.0.0.0` — reachable on both LAN and
tailnet. Syncthing GUI (`8384`) is loopback only.

## Power management

| `pmset -g` key | Value | OK? |
|---|---|---|
| `sleep` | 0 | yes — system idle-sleep disabled |
| `displaysleep` | 10 | yes — display sleeps after 10 min |
| `disksleep` | 10 | tighten to 0 |
| `powernap` | 1 | turn off (mid-idle wake/sleep churn) |
| `womp` | 1 | yes — wake on magic packet enabled |
| `tcpkeepalive` | 1 | yes |
| `standby` | 0 | yes — modern-standby off |
| `hibernatemode` | implicit 0 | yes |
| `Sleep On Power Button` | 1 | **risk** — accidental press takes infra offline |
| `autorestart` | 1 | yes |

Single permanent prevent-sleep assertion held by `powerd`
(`ExternalMedia`) because the TerraMaster is attached — independent of
the pmset config. Last 5,355 lines of `pmset -g log` (7 days) contain
**zero** sleep events.

## Disk usage to back up

| Path | Size | Disposable? |
|---|---|---|
| `~/Library/Application Support/Plex Media Server/Plug-in Support/Databases/` | 694 MB | **no** — DB is the canonical state |
| `~/Library/Application Support/Plex Media Server/Metadata/` | 1.4 GB | recoverable but expensive |
| `~/Library/Application Support/Plex Media Server/Media/` | 20 GB | recoverable but expensive |
| `~/Library/Preferences/com.plexapp.plexmediaserver.plist` | 1.2 KB | **no** — identity |
| `~/Library/Application Support/Syncthing/` | 345 MB | **no** — index DB + peer keys |
| `~/.config/torrent/` | 308 KB | **no** — `.rtorrent.rc` + session state |
| `~/.colima/` | 2.3 GB | recoverable (state can be rebuilt) |
| `/etc/cloudflared/` | <1 MB | **no** — tunnel UUID + creds JSON |
| `/Volumes/TerraMaster/` | 6.6 TiB | irreplaceable user data; out of scope for restic, in scope for "do not lose the disk" |

Restic plan in [Platform stacks](platform-stacks.md).

## Cloudflare side (TF, repo-managed)

Already in the repo as of this writing:

| File | Resources |
|---|---|
| `terraform/variables.tf` | `local.tunnels.pinelake = "fec5ca76-...cfargotunnel.com"`, `local.tunnel_ids.pinelake = "fec5ca76-..."` |
| `terraform/dns_pinelake_haus.tf` | DNS CNAMEs for `home`, `sync`, `torrent` → tunnel, proxied |
| `terraform/access.tf` (lines 116–168) | 3 Access apps — `pine_lake_ssh` (ssh-type, Nathan-only), `pine_lake_torrent` (self_hosted, Nathan-only), `pine_lake_syncthing` (self_hosted, Nathan-only) |

**Not** in the repo: any `cloudflare_zero_trust_tunnel_cloudflared_config`
for the pinelake tunnel. Ingress rules live only in
`/etc/cloudflared/config.yml` on the host. That's the drift we close
in [Cloudflare tunnel + Terraform](cloudflare-tunnel.md).

## Things flagged for the migration

- Colima is undersized (2 CPU / 2 GiB) — must grow before Komodo +
  stacks land.
- `dockernet` doesn't exist — must be created.
- No off-host backup of any state on the host. Plex DB is irreplaceable;
  Syncthing index loss would mean a full rescan of every peer; rtorrent
  session loss would mean re-checking 1.2 TB of torrent data.
- TerraMaster mount race at boot — preserve `colima-start-wait.sh`.
- cloudflared was on 2025.11.1; recheck the available release before migration.
- Two cloudflared `config.yml` files — only one is read; the other is
  a footgun.
- Tunnel name `torrent-pinelake` is no longer descriptive.
- Tailscale App Store build has no daemon watchdog and no CLI.
- LAN `192.168.1.0/24` is non-UniFi (ISP-style gateway) — different
  from bilby's `10.0.0.0/24`.
- Plex `Preferences.xml` does not exist; macOS uses
  `com.plexapp.plexmediaserver.plist`. Plist→XML translation required
  before the first containerised Plex start.
- Plex `*:32400` bound to all interfaces — confirm there's no
  UPnP/port-forward rule on the gateway leaking it publicly.
- Stale `alpine:latest` image present.
- Stale Syncthing peer entry for `alligator` (retired host).
