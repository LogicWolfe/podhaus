# Syncthing migration

Move syncthing from native Homebrew + LaunchAgent into a Komodo-managed
container without losing the index database or rotating peer keys. The
state is 345 MB, mostly the index DB; losing it forces every peer to
rescan every shared folder, which for the `pouch` folder
(6.6 TiB) is days of work.

Depends on: [Host bootstrap](host-bootstrap.md).

## Source of truth on the host

- `~/Library/Application Support/Syncthing/config.xml` — 24 KB, peer
  IDs, folder IDs, device certificates referenced
- `~/Library/Application Support/Syncthing/cert.pem` + `key.pem` —
  **device identity**. Lose these and the device ID changes; every
  peer treats it as a new node.
- `~/Library/Application Support/Syncthing/index-v0.14.0.db/` — index
  DB (most of the 345 MB)
- `~/Library/Application Support/Syncthing/syncthing.log` —
  rotated/disposable

Folders configured (from `config.xml`):

| Folder ID | Label | Host path | Type | Peers |
|---|---|---|---|---|
| `default` | Default Folder | `/Users/baxter/Sync` | sendreceive | Baxters-Mini, Wombat, alligator |
| `pouch` | Pouch | `/Volumes/TerraMaster` | **receiveonly** | Baxters-Mini, Kangaroo, alligator |

`alligator` was retired 2026-04-14 — that peer is dead. Clean out
post-migration (don't change `config.xml` mid-migration; the principle
is "preserve identity, defer cleanup").

## State preservation strategy

Bind-mount the existing state directory directly into the container at
`/var/syncthing/config` (or whatever the chosen image's config path
is). The syncthing/syncthing image expects state at
`/var/syncthing/config` by default; that's what we mount the host
`~/Library/Application Support/Syncthing/` to. **Folder paths inside
the container must match the host paths** because the index DB
references absolute paths — the safest play is to mount
`/Users/baxter/Sync` and `/Volumes/TerraMaster` to the container at
the same path strings.

Risks:

1. **Path rewrites.** If we mount `/Volumes/TerraMaster` at
   `/data/pouch` inside the container, syncthing's index thinks the
   folder is at `/Volumes/TerraMaster` (per config.xml). Two options:
   (a) mount at the same path inside the container (`/Volumes/TerraMaster:/Volumes/TerraMaster`),
   no config rewrite needed, or (b) rewrite `config.xml` to use the
   new in-container path. Option (a) is much safer for a one-shot
   cutover.
2. **uid/gid + permissions.** Native syncthing runs as `baxter` (501).
   The container has to be able to read/write `/Volumes/TerraMaster`
   (mounted noowners) and `/Users/baxter/Sync` (owned by 501). Run the
   container as `501:20`.
3. **GUI loopback binding.** Current native GUI listens
   `127.0.0.1:8384`. In a container, we either:
   - publish `127.0.0.1:8384:8384` (matches today, tunnel reaches via
     host `127.0.0.1`)
   - join `dockernet` and let cloudflared reach via `http://syncthing:8384`
     (cleaner; matches bilby pattern)
   Default: dockernet + cloudflared via container DNS. Tunnel ingress
   migration in [Cloudflare tunnel + Terraform](cloudflare-tunnel.md).
4. **Sync ports.** Syncthing's data ports (`*:22000` TCP+UDP) need to
   reach the public internet. In a container, that means
   `network_mode: host` OR explicit port publishes. Bilby's
   `syncthing` runs `network_mode: host` to handle multicast discovery
   and direct connections; same pattern here.
5. **Conflict with `network_mode: host` and dockernet** — they're
   mutually exclusive. Bilby's syncthing uses `host` mode and
   cloudflared reaches it via `172.18.0.1:8384`. Same pattern for
   pinelake. So syncthing on dockernet was wrong above; correct it.

### Corrected approach: `network_mode: host`

```yaml
services:
  syncthing:
    container_name: syncthing
    image: syncthing/syncthing:latest
    user: "501:20"
    restart: unless-stopped
    network_mode: host
    environment:
      PUID: "501"
      PGID: "20"
      STGUIADDRESS: "127.0.0.1:8384"
    volumes:
      - /Users/baxter/Library/Application Support/Syncthing:/var/syncthing/config
      - /Users/baxter/Sync:/Users/baxter/Sync
      - /Volumes/TerraMaster:/Volumes/TerraMaster
    labels:
      autoheal: "true"
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8384/rest/system/status >/dev/null || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 60s
```

`stack.toml`:

```toml
[stack]
server = "pinelake"
linked_repo = "podhaus"
run_directory = "/etc/komodo/repos/podhaus/syncthing/pinelake"
```

`STGUIADDRESS=127.0.0.1:8384` preserves the loopback-only GUI binding.
Tunnel reaches it via `172.18.0.1:8384` from inside cloudflared
(matches Plex pattern in [Plex](plex.md)).

**Note**: syncthing healthcheck via the REST API typically requires
the API key. The example above hits `/rest/system/status` which
doesn't require auth on default config. Verify on the actual deploy;
if it fails, fall back to `nc -z 127.0.0.1 8384`.

## Cutover sequence

1. **Pre-flight**:
   - Capture device ID (from `config.xml` `<device id="…">`)
   - Confirm all peers are online and recent sync timestamps look
     healthy (bilby periphery container, Kangaroo, Wombat,
     Baxters-Mini)
   - Pause syncing globally from the GUI (Actions → Pause All) to get
     a quiescent index
2. **Stop native daemon**:
   ```sh
   launchctl unload ~/Library/LaunchAgents/homebrew.mxcl.syncthing.plist
   pgrep -fl syncthing  # confirm empty
   ```
3. **Snapshot state** (belt-and-braces above the step-1 bootstrap
   snapshot):
   ```sh
   rsync -a ~/Library/Application\ Support/Syncthing/ \
     /Volumes/TerraMaster/_pinelake-migration-snapshots/syncthing-prebr/
   ```
4. **Deploy** `syncthing/pinelake` via Komodo (`./komodo-sync`).
5. **Verify**:
   - `docker logs syncthing` — should report `Loading folder …`,
     no "device ID changed" warning
   - GUI at `127.0.0.1:8384` from host shows the same device ID as
     captured pre-flight
   - All peers reachable, none "disconnected" beyond the brief restart
   - Folder hashes / sequence numbers stable (no full rescan)
6. **Resume** all folders via the GUI (Actions → Resume All).
7. **Retire native install** *after* a 24-h soak:
   ```sh
   rm ~/Library/LaunchAgents/homebrew.mxcl.syncthing.plist
   brew uninstall syncthing
   ```
   Leave `~/Library/Application Support/Syncthing/` in place — it's
   the running container's state directory.
8. **Clean stale `alligator` peer** from each folder's device list via
   the GUI. (Doing this is the only "non-identity-preserving" step;
   keep it after the soak so rollback paths remain simple.)

## Risks and rollback

- Rollback path: stop the container, restore `~/Library/LaunchAgents/`
  plist + `brew install syncthing`, `launchctl load …`. State dir
  hasn't moved.
- If the device ID changes despite preserving cert/key, every peer
  sees a new device and needs to re-accept it. This is recoverable
  but noisy. Cause is almost always a regenerated cert; ensure the
  mount is read-write and the existing cert.pem/key.pem are present
  before first container start.
- If the index DB version mismatches the container's syncthing
  version, syncthing migrates it in place on first start. This is a
  one-way migration — once migrated, downgrading the native build
  would refuse to load the newer-format DB. Take the snapshot in
  step 3 explicitly to cover this rollback case.

## Backup

Once Backrest is up on pinelake, add a `syncthing-pinelake` plan:

- `/Users/baxter/Library/Application Support/Syncthing/` (345 MB)
- Excludes: `syncthing.log*`, anything matching the `*.tmp` pattern
- Schedule: 04:00 AWST, 14/4/6 retention (matches kangaroo's syncthing
  plan)

Detail in [Platform stacks](platform-stacks.md).

## Acceptance criteria

- `docker ps` shows `syncthing` container on `network_mode: host`,
  healthy
- Device ID unchanged from pre-cutover capture
- All non-alligator peers connected within 5 minutes of cutover
- No full-folder rescan triggered (sequence numbers continuous)
- `sync.pinelake.haus` returns the Syncthing GUI through Cloudflare
  Access
- Native syncthing binary uninstalled (after soak)

## Open items deferred

- Whether to fold pinelake's syncthing into a shared compose with
  kangaroo's (`syncthing/compose.shared.yaml`) — depends on how
  similar the config ends up. Default: separate, can converge later.
- Whether to clean stale `alligator` device from `config.xml`
  pre-cutover or post-cutover. Post-cutover is safer.
