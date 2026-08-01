# Flood / rtorrent migration

The simplest stream. Existing state is a single `docker run` invocation
managed by `~/.config/torrent/run_container.sh`; target is a real
compose stack under Komodo at `flood/pinelake/`. State is small (308 KB
config + session, 1.2 TB downloaded torrents), and the migration is
mostly cosmetic.

Depends on: [Host bootstrap](host-bootstrap.md) (dockernet, periphery).

## Source of truth on the host

- `/Users/baxter/.config/torrent/.rtorrent.rc` — 6.1 KB, the actual
  rtorrent config
- `/Users/baxter/.config/torrent/.local/share/rtorrent/.session/` —
  rtorrent session state (one file per active torrent, plus
  `*.torrent.libtorrent_resume` files)
- `/Users/baxter/.config/torrent/.local/share/rtorrent/{watch,download,log}/`
  — empty/quiet by convention
- `/Volumes/TerraMaster/Torrents/` — 1.2 TB downloaded data
- `/Users/baxter/.config/torrent/run_container.sh` — current launch
  recipe (to be retired)

## State preservation strategy

Bind mounts will continue to point at the same host paths. **No data
moves.** The container restarts onto the same `/config` and `/data`
volumes; rtorrent re-reads its session on start; nothing rehashes.

Risks:

1. **uid/gid mismatch.** The current launcher computes
   `<vm-gid-of-/Users/baxter>` at runtime via
   `colima ssh -- stat -c %g /Users/baxter`. After resizing colima
   (step 2 of host bootstrap) the gid may change. Capture the gid
   **before** the colima resize and verify it's stable after — if not,
   the new compose has to use the new gid, and the existing
   `.torrent.libtorrent_resume` files need their ownership matched
   (otherwise rtorrent refuses to resume those torrents and starts
   them as new-and-unhashed).
2. **`--auth none` re-exposure.** Flood ships with no auth; Pomerium's
   Nathan-only route is the gate. Verify the route through Numbat before
   retiring cloudflared.
3. **Container name collision.** Existing container is
   `rtorrent-flood` on the default `bridge`. New compose container
   will be `flood` (matching bilby's naming) on `dockernet`. Stop the
   old container before starting the new one; otherwise Docker
   complains about port 3000 being held.

## Compose layout

`flood/pinelake/compose.yaml`:

```yaml
services:
  flood:
    container_name: flood
    image: jesec/rtorrent-flood:latest
    user: "501:${PINELAKE_BAXTER_VM_GID}"
    restart: unless-stopped
    networks:
      - dockernet
    environment:
      HOME: /config
      FLOOD_OPTION_HOST: 0.0.0.0
      FLOOD_OPTION_RTORRENT: "true"
    command:
      - --auth=none
      - --rtconfig=/config/.rtorrent.rc
      - --rtsocket=/tmp/rtorrent.sock
      - --allowedpath=/data
    volumes:
      - /Users/baxter/.config/torrent:/config
      - /Volumes/TerraMaster/Torrents:/data
    labels:
      autoheal: "true"
      podhaus.stack-content-hash: ${STACK_CONTENT_HASH:-unset}
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:3000/api/auth/verify || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s

networks:
  dockernet:
    external: true
```

`flood/pinelake/stack.toml`:

```toml
[[stack]]
name = "pinelake-flood"
tags = ["pinelake", "podhaus"]

[stack.config]
server = "pinelake"
linked_repo = "podhaus-pinelake"
run_directory = "flood/pinelake"

environment = """
PINELAKE_BAXTER_VM_GID=[[PINELAKE_BAXTER_VM_GID]]
"""

[[variable]]
name = "PINELAKE_BAXTER_VM_GID"
value = "<captured value>"
description = "Group ID that owns Pinelake's torrent files inside Colima"
```

`PINELAKE_BAXTER_VM_GID` is host-specific but non-secret, so it stays
with the stack as a TOML variable. Don't add it to `komodo-start`.

## Healthcheck

Flood's `/api/auth/verify` returns 200 even with `--auth none`. If that
proves wrong, fall back to a simple `nc -z 127.0.0.1 3000` or a curl
against the static page (`/`).

## Cutover sequence

1. **Pre-flight**: capture
   `colima ssh -- stat -c %g /Users/baxter` value. Confirm
   `torrent.pinelake.haus` is loading the Flood UI behind Access.
   Confirm rtorrent has no active hash-checks in progress
   (`/api/torrents` count stable, no `hashing` state).
2. **Stop legacy container**: `docker stop rtorrent-flood &&
   docker rm rtorrent-flood`. The container's
   `/Users/baxter/.config/torrent/.local/share/rtorrent/.session/` is
   the live session — leaving it untouched is essential.
3. **Deploy via Komodo**: register `flood/pinelake` through
   `./komodo-sync`. Stage 2 treats a brand-new stack as a full deploy.
4. **Verify**: Flood UI loads at `torrent.pinelake.haus`, active
   torrents show as resumed (not re-hashed), `nc -zv 127.0.0.1 3000`
   from host. Existing downloads in `/data` accessible.
5. **Retire**:
   - `rm /Users/baxter/.config/torrent/run_container.sh` (or rename
     `.archive` for safety)
   - `docker rmi alpine:latest jesec/rtorrent-flood:<old-sha>` to free
     space
   - Update [Flood runbook](/runbooks/flood.html) with the new compose
     location

## Numbat route

The Pinelake rathole client connects to `flood:3000` on dockernet and exposes
only that named service to Numbat. Pomerium applies the Nathan-only route at
`torrent.pinelake.haus`. Keep the old cloudflared path until the new route is
verified, then remove its daemon and config.

## Backup

Once Backrest is up on pinelake, add a `flood-pinelake` plan covering:

- `/Users/baxter/.config/torrent/` (308 KB, daily, 14/4/6 retention)

Excluded from backup:

- `/Volumes/TerraMaster/Torrents/` — too large; the data is replaceable
  (re-fetch torrents). Optionally include the small `.torrent` files
  themselves but not the data.

Detail in [Platform stacks](platform-stacks.md).

## Acceptance criteria

- `docker ps` shows `flood` container on `dockernet`, healthy
- `torrent.pinelake.haus` returns the Flood UI through Cloudflare
  Access
- `curl -fsS http://flood:3000/api/torrents` from another container on
  dockernet returns the same torrent list as before cutover
- No rehashing observed; all previously-completed torrents still
  marked complete
- Old `run_container.sh` archived or removed; no lingering
  `rtorrent-flood` container

## Open items deferred

- Whether flood should join a `flood/compose.shared.yaml` pattern with
  bilby's existing flood (current bilby flood is single-host) — depends
  on whether the configs are identical enough. Recommendation: keep
  separate single-host until/unless we see real duplication.
