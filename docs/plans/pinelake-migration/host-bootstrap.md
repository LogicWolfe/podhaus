# Host bootstrap

The platform foundation everything else builds on. Brings pinelake from
"a Mac mini with hand-rolled docker run" to "a managed Komodo Periphery
host with dockernet, sensible sleep config, a Tailscale daemon, and a
working `tf`-side handle." Nothing service-level lands until this is
done.

## Goal state

- Colima sized appropriately for the eventual stack set.
- `dockernet` (`172.18.0.0/16`) created and persistent.
- Komodo Periphery running as a container on pinelake, registered in
  Core (linked-repo mode like kangaroo).
- `pmset` + `caffeinate` belt-and-braces so the host stays awake.
- Tailscale `tailscaled` LaunchDaemon (replacing App Store IPNExtension).
- `cloudflared` upgraded to current.

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
The subnet must be exactly `172.18.0.0/16` — every podhaus stack
assumes containers reach each other by name within this network and
that the host-network services are reachable at `172.18.0.1:<port>`
from inside containers (this is the cloudflared → host-Plex /
host-Syncthing path on bilby; same convention here).

`rtorrent-flood` is still on the default `bridge` network at this
point. It moves to dockernet in [Flood](flood.md), not here — keep
this stream focused on the platform.

## Step 4 — Komodo Periphery on pinelake

Linked-repo mode (like kangaroo) — Komodo Core on bilby drives this,
pinelake's periphery clones the repo itself.

### Komodo side (bilby, repo)

In `komodo/sync/servers.toml`, add:

```toml
[[server]]
name = "pinelake"
[server.config]
description = "Apple M1 Mac mini, second household. macOS + colima."
address = "https://pinelake.haus:8120"   # via tailscale if LAN routing not available
enabled = true
auto_prune = true
# Auth model — depends on Periphery v2 decision (open question #7 in index)
# Option A (current/legacy): periphery_passkeys via env
# Option B (v2 keypair):     periphery_public_key = "<pinelake pubkey>"
```

In `komodo/sync/repos.toml`, add:

```toml
[[repo]]
name = "podhaus"
[repo.config]
server = "pinelake"
git_provider = "github.com"
git_account = "LogicWolfe"
repo = "LogicWolfe/podhaus"
branch = "main"
# Polling cadence + webhook target inherit from existing kangaroo entry
```

### Pinelake side (host)

Mirror the `kangaroo_bootstrap` script (see top-level of repo) into
`pinelake_bootstrap` if it's not yet host-portable. Differences from
kangaroo:

- Runs on macOS, not QTS — paths under `/Users/baxter/` not
  `/share/CACHEDEV*_DATA/`.
- Colima provides the docker socket; bind-mount it from
  `~/.colima/default/docker.sock` into the periphery container.
- The compose's `repo_dir` setting points at `/etc/komodo/repos/podhaus`
  inside the periphery container — periphery clones the linked repo
  itself there.
- `.env` (containing the periphery passkey or v2 private key) is
  rendered by `op run --env-file=…` from the 1Password `Komodo
  Periphery (pinelake)` item.
- Crontab `@reboot` entry that re-runs `docker compose up -d` against
  the periphery compose (belt-and-braces over Docker's own restart).
  Alternative: launchd plist that depends on `io.colima.start.plist`.

The Periphery compose file lands as
`komodo-periphery/pinelake/compose.yaml` + `stack.toml` (this can
self-host once Core can reach it; first start is manual via
`pinelake_bootstrap`).

### Verify

From bilby's Komodo UI: pinelake shows green in the Servers list,
Periphery version matches, latency reasonable. From pinelake's
periphery logs: handshake succeeded, no auth errors.

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

## Step 6 — Tailscale: replace App Store with `tailscaled` daemon

Reason: the App Store IPNExtension has no LaunchDaemon, no watchdog,
no exposed CLI by default. A daemon-based install lets Gatus probes
and `tailscale serve` work, and lets a crashed daemon get restarted by
launchd.

```sh
# 1. Capture current state for rollback
tailscale ip -4   # via "Install CLI" in app first, OR read from app menu
# Note the current authkey/tags.

# 2. Sign out of the App Store app
#    Tailscale.app menu -> Account -> Log out

# 3. Quit App Store app, then remove
#    (App Store removal works; do not delete the user-extension state
#    forcibly — let macOS clean it up)

# 4. Install Homebrew daemon-based tailscale
brew install tailscale
sudo brew services start tailscale

# 5. Authenticate as the same node identity
sudo tailscale up --hostname=pinelake \
  --advertise-tags=tag:server \
  --accept-routes \
  --accept-dns=true
```

The node should rejoin with the **same** tailnet IP (`100.124.202.28`)
if the authkey/account is the same; otherwise the IP rotates, which
means Gatus/Komodo configs that pin the IP need updating. Prefer
MagicDNS names everywhere instead of raw IPs to avoid this.

Verify:
- `tailscale status` shows the node as `pinelake`
- `tailscale ip -4` returns the expected address
- From bilby (also on tailnet): `tailscale ping pinelake`
- Reboot the host; confirm `tailscaled` comes up via launchd

### Optional: `tailscale serve` for Plex

If decision #3 in the index lands as "Plex over tailnet, no public
ingress", add:

```sh
sudo tailscale serve --bg --https=443 http://localhost:32400
```

That exposes Plex at `https://pinelake.<tailnet>.ts.net` with a real
TLS cert, no port-forward, no Cloudflare.

## Step 7 — Upgrade cloudflared

Just `brew upgrade cloudflared`. Don't touch the config or the daemon
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

## Step 9 — verify dockernet from a probe

```sh
docker run --rm --network dockernet alpine sh -c \
  'apk add --no-cache curl >/dev/null && curl -sI http://172.18.0.1:32400 | head -1'
```

Should return `HTTP/1.0 200 OK` (Plex's web UI responds even
unauthenticated). Confirms the path that the migrated cloudflared (and
the per-service ingress rules) will use to reach the host-network
Plex.

## Acceptance criteria

- `colima status` shows 6 CPU / 12 GiB / 200 GiB
- `docker network inspect dockernet` shows `172.18.0.0/16` with gateway
  `172.18.0.1`
- Komodo Core UI shows pinelake green, periphery version reported
- `pmset -g | grep -E 'sleep|powernap|standby'` shows `sleep 0`,
  `powernap 0`, `standby 0`
- `launchctl print system/haus.podhaus.caffeinate` shows running
- `tailscale status` invoked from a shell (CLI installed)
- `cloudflared --version` reports 2026.3.x (or current)
- `docker compose version` works on the host

None of the above touches a service stack — those are in their own
streams.

## Open items deferred

- Komodo Periphery auth model (open question #7 in index)
- Plex public exposure decision (informs `tailscale serve` step)
- Whether `pinelake_bootstrap` is a separate script or a parameterised
  evolution of `kangaroo_bootstrap`
