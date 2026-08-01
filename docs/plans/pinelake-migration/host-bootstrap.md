# Host bootstrap

The platform foundation everything else builds on. Brings pinelake from
"a Mac mini with hand-rolled docker run" to "a managed Komodo Periphery
host with dockernet, sensible sleep config, a Tailscale daemon, and a
working Terraform-side handle." Nothing service-level lands until this is
done.

## Goal state

- Colima sized appropriately for the eventual stack set.
- `dockernet` (`172.18.0.0/16`) created and persistent.
- Komodo Periphery running as a container on pinelake, registered in
  Core (linked-repo mode like kangaroo).
- `pmset` + `caffeinate` belt-and-braces so the host stays awake.
- A supported system-managed Tailscale installation on the podhaus management
  tailnet, replacing the per-user App Store IPNExtension on its current
  separate tailnet.
- `cloudflared` upgraded to the release selected at execution time.

## Step 1 — back up everything stateful

Before any of the rest happens, snapshot the host so any of these
changes can be unwound. Rsync (`-a --delete`) the following directories
to bilby's `/mnt/jump/pinelake-prebootstrap/` (or a temp external
drive):

```
/Users/baxter/Library/Application Support/Plex Media Server/
/Users/baxter/Library/Preferences/com.plexapp.plexmediaserver.plist
/Users/baxter/Library/Application Support/Syncthing/
/Users/baxter/.config/torrent/
/etc/cloudflared/
/usr/local/bin/colima-start-wait.sh
/Library/LaunchDaemons/io.colima.start.plist
/Library/LaunchDaemons/com.cloudflare.cloudflared.plist
~/Library/LaunchAgents/homebrew.mxcl.syncthing.plist
~/.colima/default/colima.yaml
```

This snapshot is the rollback path for the entire migration, not just
this stream. **Don't proceed without it.** Plex state alone (22 GB) is
the highest-stakes part — confirm the rsync completed by comparing
file counts + a sample of sha256s.

## Step 2 — resize colima

Edit `~/.colima/default/colima.yaml`:

```yaml
cpu: 6              # was 2
memory: 12          # was 2 (GiB)
disk: 200           # was 100
```

Then `colima stop && colima start`. Colima preserves the VM disk
contents on resize. Verify with `colima status` and `docker info`
showing 6 CPU / 12 GiB.

**Important:** the running `rtorrent-flood` container will be stopped
during the colima restart and brought back by Docker's
`--restart unless-stopped`. Confirm it returns and the Flood UI is
healthy at `torrent.pinelake.haus` before continuing.

If 6/12/200 turns out wrong:
- CPU: bound by what the M1 has (8 physical), leave 2 for the host
- RAM: bound by 16 GiB total, leave at least 4 GiB for the host +
  native Plex if Plex stays native through migration
- Disk: 200 GiB is generous; restic chunks for backup target may push
  it higher if the local restic repo lives inside the VM (it shouldn't
  — see [Platform stacks](platform-stacks.md))

## Step 3 — create dockernet

```sh
docker network create \
  --driver bridge \
  --subnet 172.18.0.0/16 \
  --gateway 172.18.0.1 \
  --attachable \
  dockernet
```

Mark it idempotent in any bootstrap script — `docker network inspect
dockernet >/dev/null 2>&1 || docker network create ...`.

Confirm `docker network ls` and `docker network inspect dockernet`.
The subnet must be exactly `172.18.0.0/16` so Pinelake containers can use the
same service-name convention as the rest of podhaus. On Colima,
`172.18.0.1` is the Linux VM's bridge gateway, not the macOS host. Native
macOS services and native cloudflared must use proven Colima port forwarding;
do not copy bilby's Linux host-service gateway pattern.

`rtorrent-flood` is still on the default `bridge` network at this
point. It moves to dockernet in [Flood](flood.md), not here — keep
this stream focused on the platform.

## Step 4 — Komodo Periphery on pinelake

Use the current v2 outbound model. Pinelake's Periphery dials Core over
the tailnet, authenticates with its private key, and clones a host-specific
Linked Repo. Nothing listens on pinelake port 8120 from the LAN or internet.

### Komodo side (bilby, repo)

In `komodo/sync/servers.toml`, add:

```toml
[[server]]
name = "pinelake"
description = "Apple M1 Mac mini, second household. macOS + Colima. v2 outbound: Periphery dials Core."
tags = ["pinelake", "podhaus"]

[server.config]
address = ""
enabled = true
disk_warning = 85.0
disk_critical = 95.0
```

Add `komodo/keys/pinelake-periphery.pub` to Core's trusted Periphery
public-key list using the same path as Kangaroo and Kookaburra.

In `komodo/sync/repos.toml`, add:

```toml
[[repo]]
name = "podhaus-pinelake"
[repo.config]
server = "pinelake"
git_provider = "github.com"
git_account = "LogicWolfe"
repo = "LogicWolfe/podhaus"
branch = "main"
```

### Pinelake side (host)

Use `kangaroo_bootstrap` and `kookaburra_bootstrap` as references for a
new idempotent `pinelake_bootstrap`. Pinelake differs in these ways:

- Runs on macOS, not QTS — paths under `/Users/baxter/` not
  `/share/CACHEDEV*_DATA/`.
- Colima owns the Docker daemon. The compose bind is
  `/var/run/docker.sock:/var/run/docker.sock` from the daemon's view,
  matching ordinary Docker-in-Docker control stacks.
- Generate `periphery.key` once on pinelake, copy the matching public key
  into `komodo/keys/`, and copy Core's public key to the host. Mount both
  under `/config/keys`, following the existing Periphery composes.
- Set `PERIPHERY_CORE_ADDRESSES` to
  `ws://bilby-podnet.tail9ceb.ts.net:9120` and
  `PERIPHERY_CONNECT_AS=pinelake`. Prove Colima's containers can resolve
  the MagicDNS FQDN before starting Periphery. If they cannot, configure
  Colima's Docker daemon to forward unknown names to `100.100.100.100` and a
  public fallback, then re-test. Preserve Docker's embedded resolver and never
  add per-container `dns:` overrides.
- Persist `/etc/komodo` and `/config/keys` under a stable host directory.
- Let the existing Colima LaunchDaemon start the VM. Use
  `restart: unless-stopped` for Periphery and add a dependent LaunchDaemon
  only if Colima doesn't restore the container reliably after a real reboot.

The Periphery compose lives under `pinelake/periphery/` and remains
bootstrap-managed. It can't manage itself because Core loses the host if
Periphery is down.

### Verify

From bilby's Komodo UI, pinelake shows green in the Servers list and the
Periphery version matches the fleet. The pinelake Periphery logs show a
successful outbound noise handshake with no reconnect loop. No host port
8120 is published.

## Step 5 — sleep / power management

`pmset -g` is already most of the way there — the only real risk is
the power button. Apply these settings via a one-shot script and pin
them so an OS upgrade can't reset them silently:

```sh
sudo pmset -a sleep 0
sudo pmset -a displaysleep 10
sudo pmset -a disksleep 0
sudo pmset -a powernap 0
sudo pmset -a standby 0
sudo pmset -a hibernatemode 0
sudo pmset -a autopoweroff 0
sudo pmset -a tcpkeepalive 1
sudo pmset -a womp 1
defaults write com.apple.loginwindow PowerButtonSleepsSystem -bool no
```

`defaults write com.apple.loginwindow PowerButtonSleepsSystem -bool no`
is the key one — current `Sleep On Power Button = 1` means a bumped
power button takes the infra offline.

### LaunchDaemon for `caffeinate -i -s`

Belt-and-braces against a future OS upgrade re-enabling sleep. The
`-i` flag prevents idle **system** sleep without affecting
**display** sleep — that's exactly what we want.

Drop at `/Library/LaunchDaemons/haus.podhaus.caffeinate.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>           <string>haus.podhaus.caffeinate</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>-s</string>
  </array>
  <key>RunAtLoad</key>       <true/>
  <key>KeepAlive</key>       <true/>
  <key>StandardOutPath</key> <string>/var/log/haus.podhaus.caffeinate.log</string>
  <key>StandardErrorPath</key><string>/var/log/haus.podhaus.caffeinate.log</string>
</dict>
</plist>
```

Load: `sudo launchctl bootstrap system /Library/LaunchDaemons/haus.podhaus.caffeinate.plist`.

Verify: `pmset -g assertions` shows `PreventUserIdleSystemSleep` from
caffeinate.

**Do not** add `-d` to the args — that prevents display sleep, which
contradicts the goal.

## Step 6: Tailscale, replace the per-user App Store runtime

Reason: the audited App Store IPNExtension has no system LaunchDaemon or
exposed CLI and is on a different tailnet from podhaus. Pinelake Periphery
needs the management path before an interactive user logs in.

```sh
# 1. Capture the old tailnet state for rollback
tailscale ip -4   # via "Install CLI" in app first, OR read from app menu
# Record the old account, device name, and IP.

# 2. Sign out of the App Store app
#    Tailscale.app menu -> Account -> Log out

# 3. Quit App Store app, then remove
#    (App Store removal works; do not delete the user-extension state
#    forcibly — let macOS clean it up)

# 4. Install the current official standalone macOS distribution and enable
#    its supported unattended/system mode. Do not assume the Homebrew
#    open-source daemon provides a system-wide macOS VPN.

# 5. Using that installation's CLI, enrol into the podhaus tailnet with
#    hostname pinelake and the TF-managed tag:podnet auth key from:
op read 'op://Homelab/Tailscale Auth Key/credential'
```

The existing `100.124.202.28` address belongs to the old tailnet and is not
expected to survive. No podhaus config should depend on the new address.
Use the MagicDNS name everywhere and verify the node carries
`tag:podnet`, which is embedded in the Terraform-managed auth key.

Verify:
- `tailscale status` shows the node as `pinelake`
- `tailscale ip -4` returns an address on the podhaus tailnet
- From bilby (also on tailnet): `tailscale ping pinelake`
- Reboot without an interactive login; confirm the Tailscale node and
  Pinelake Periphery reconnect

### Optional: `tailscale serve` for Plex

If decision #3 in the index lands as "Plex over tailnet, no public
ingress", add:

```sh
sudo tailscale serve --bg --https=443 http://localhost:32400
```

That exposes Plex at `https://pinelake.<tailnet>.ts.net` with a real
TLS cert, no port-forward, no Cloudflare.

## Step 7 — Upgrade cloudflared

Run `brew upgrade cloudflared`. Don't touch the config or the daemon
plist yet — config migration is its own stream
([Cloudflare tunnel + Terraform](cloudflare-tunnel.md)). After the
upgrade, `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`
to bounce the daemon and confirm reconnection.

## Step 8 — install `docker compose` plugin

Periphery's compose is internal — but a human shell on pinelake
shouldn't be without `docker compose` either. `brew install
docker-compose` and add the plugin path to `~/.docker/config.json`:

```json
{
  "cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]
}
```

Verify: `docker compose version`.

## Step 9: Verify dockernet and Mac port forwarding

```sh
docker run --rm --network dockernet --name pinelake-net-probe alpine ip route
```

Confirm the probe receives an address in `172.18.0.0/16`. Separately launch a
disposable HTTP container with a loopback-only published port and confirm the
Mac can reach it at `127.0.0.1`. That is the path native cloudflared will use
for containerised Flood and any later Syncthing migration.

## Acceptance criteria

- `colima status` shows 6 CPU / 12 GiB / 200 GiB
- `docker network inspect dockernet` shows `172.18.0.0/16` with gateway
  `172.18.0.1`
- Komodo Core UI shows pinelake green, periphery version reported
- `pmset -g | grep -E 'sleep|powernap|standby'` shows `sleep 0`,
  `powernap 0`, `standby 0`
- `launchctl print system/haus.podhaus.caffeinate` shows running
- `tailscale status` invoked from a shell (CLI installed)
- `cloudflared --version` reports the release chosen at execution time
- `docker compose version` works on the host

None of the above touches a service stack — those are in their own
streams.

## Open items deferred

- Plex public exposure decision (informs the optional `tailscale serve` step)
- Whether `pinelake_bootstrap` is a separate script or a parameterised
  evolution of `kangaroo_bootstrap`
