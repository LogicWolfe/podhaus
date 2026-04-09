# Plex Containerization

> **Status**: Running. Docker NFS volumes mount directly from OrbStack's VM to the NAS, bypassing macOS VirtioFS.

## Pre-Migration State

| | |
|---|---|
| **Machine** | Mac mini M1, 16GB RAM, hostname `bilby`, IP `10.0.0.119` |
| **Plex** | v1.43.1.10561, running natively from `/Applications/Plex Media Server.app` |
| **Data** | 58GB total — 44GB library database, 12GB metadata, 220MB plugins |
| **Media** | NAS at `10.0.0.25`, NFS-mounted at `/Users/Shared/Pouch` (10GbE) |
| **Libraries** | 11 sections, all paths under `/Users/Shared/Pouch/*` |
| **Clients** | Active LAN connections on port 32400 |
| **Plugins** | Trakttv, Sub-Zero |
| **DB backups** | `/Users/Shared/Pouch/plex_db_backups` |

### Library Paths in Database

| Library | Path |
|---|---|
| Movies | `/Users/Shared/Pouch/Movies` |
| TV Shows | `/Users/Shared/Pouch/TV` |
| Anime | `/Users/Shared/Pouch/Anime` |
| Kids Movies | `/Users/Shared/Pouch/Kids/Movies` |
| Kids TV | `/Users/Shared/Pouch/Kids/TV` |
| Kids Video | `/Users/Shared/Pouch/Kids/Videos` |
| Sports | `/Users/Shared/Pouch/Sports`, `/Users/Shared/Pouch/Races` |
| Documentary Movies | `/Users/Shared/Pouch/Documentaries` |
| Documentary TV | `/Users/Shared/Pouch/Documentary Series` (also at `/Volumes/Macintosh HD/Users/Shared/Pouch/Documentary Series`) |
| Ελληνικές Ταινίες | `/Users/Shared/Pouch/Ελληνικές Ταινίες` |

### Critical Identifiers

Canonical source is `Preferences.xml` on the Jump mount at `/Users/Shared/Jump/plex/Library/Application Support/Plex Media Server/Preferences.xml`. Verify with:
```
grep MachineIdentifier "/Users/Shared/Jump/plex/Library/Application Support/Plex Media Server/Preferences.xml"
```
Cross-check against plex.tv: `curl -s "https://plex.tv/api/servers" -H "X-Plex-Token: <token>"` — the `machineIdentifier` should match.

## Design Decisions

### Config lives in podhaus repo

All container config lives in `plex/` within `~/repos/podhaus`, following the existing pattern of `<service>/compose.yaml`. No `stack.toml` is created — Komodo's ResourceSync auto-discovers any directory with a `stack.toml`, and we don't want Plex picked up yet. Values are hardcoded in the compose file (matching the pattern of other compose files like flood), not interpolated via env vars.

### Config/database on Jump, media on Pouch

Two NAS mounts with very different performance profiles:

- **`/Users/Shared/Jump`** (NFS, 382GB, fast) — Plex config, database (44GB), metadata. This is where container state lives.
- **`/Users/Shared/Pouch`** (NFS, 29TB, bulk) — Media files only.

The 44GB SQLite database lives on Jump. SQLite random IO latency over NFS will be higher than local SSD (~0.5-1ms vs ~0.01ms per round-trip), but Jump's smaller dedicated volume should have better IOPs than the 29TB media array. If library browsing or search becomes sluggish, config can be moved to local SSD later.

### Docker NFS volumes, not macOS bind mounts

Both NFS mounts are Docker volumes that mount directly from OrbStack's Linux VM to the NAS (10.0.0.25) using NFSv4.1. This bypasses macOS's NFS client and OrbStack's VirtioFS file-sharing layer entirely.

**Why:** After macOS sleep, VirtioFS caches stale inode references to NFS mount points. The container sees dead mounts even after restart, because the stale state lives in OrbStack's VM file-sharing layer. Docker NFS volumes avoid this — the Linux NFS client reconnects automatically on wake (v4.1 session recovery), and a container restart gets fresh mount handles if needed.

**Trade-off:** Direct NFS from the VM goes through OrbStack's NAT at MTU 1500 (no jumbo frames), so peak sequential throughput is lower than macOS NFS with MTU 9000. For media streaming this is far more bandwidth than needed (4K remux peaks at ~12.5 MB/s).

The macOS autofs NFS mounts in `/etc/auto_nfs` remain for Finder and other host tools.

### Identity mount for zero library reconfiguration

The Pouch volume is mounted at `/Users/Shared/Pouch` inside the container — the same path as the old bind mount. All library paths in the Plex database remain valid with zero reconfiguration.

### Host network mode

Plex uses many ports beyond 32400 (GDM discovery on 32410-32414/udp, Bonjour on 5353/udp, Roku companion on 8324). Host networking avoids mapping all of them individually and lets GDM server discovery work for LAN clients. This matches the pattern used by home-assistant in the repo.

No `ADVERTISE_IP` — with host networking, Plex auto-detects its network interfaces for both LAN discovery (GDM) and remote access (via plex.tv). `ADVERTISE_IP` is mainly needed in bridge mode where the container's internal IP is unreachable. If OrbStack's host networking causes Plex to detect the wrong interface, set custom URLs via the Plex UI (Settings > Network > Custom server access URLs) rather than hardcoding in compose.

If host mode doesn't expose port 32400 on the LAN IP through OrbStack, fall back to bridge mode with explicit port mapping (see fallback section below).

### No hardware transcoding concern

macOS on Apple Silicon has never supported Plex hardware transcoding (Intel Quick Sync only). No regression from containerizing.

### Transcode in tmpfs

A 4GB tmpfs mount at `/transcode` keeps transcode temp files in RAM. The existing `Preferences.xml` already has `TranscoderTempDirectory="/transcode"`. Typical single transcode uses 1.5-2.2GB.

## Repository Structure

```
~/repos/podhaus/
├── plex/
│   ├── compose.yaml     # Docker Compose definition (Plex + backup sidecar + NFS volumes)
│   ├── backup.sh        # Database backup with integrity check and auto-recovery
│   ├── MIGRATION.md     # This file
│   └── NFS.md           # NFS mount setup and benchmarks
├── autoheal/
│   └── compose.yaml     # Restarts unhealthy containers
├── flood/
│   ├── compose.yaml
│   └── stack.toml
├── home-assistant/
│   └── ...
└── ...
```

No `stack.toml` — Komodo's ResourceSync auto-discovers and deploys any directory with a `stack.toml`. Without one, Plex stays invisible to Komodo until we're ready to migrate it.

No `.env` file or `${VAR}` interpolation — following the pattern of other compose files in the repo (e.g. flood hardcodes `/mnt/NFSPouch:/data`), paths are written directly. The `MEDIA_DIR` variable in `variables.toml` is vestigial and unused by any current compose file.

### Troubleshooting: host networking not exposing to LAN

OrbStack's `network_mode: host` should expose ports on the Mac's LAN IP. If LAN clients can't reach Plex, fall back to bridge mode with explicit port mapping and `ADVERTISE_IP: http://10.0.0.119:32400/`.

## Execution

### Phase 1: Prepare

- [x] Ensure OrbStack is running and `docker ps` works
- [x] Verify `/Users/Shared/Pouch` and `/Users/Shared/Jump` are NFS-mounted and accessible
- [x] Create config directory on Jump

### Phase 2: Bulk Copy (Plex still running, minimises downtime)

- [x] Initial rsync of Plex data while Plex is still serving clients

### Phase 3: Cut Over (downtime starts)

- [x] Disable Plex auto-start
- [x] Stop native Plex
- [x] Final rsync to Jump
- [x] Verify Preferences.xml present on Jump

### Phase 4: Start Container

- [x] Start container with `docker compose up -d`
- [x] Verify logs

### Phase 5: Verify

- [x] Web UI loads at `http://localhost:32400/web`
- [x] Identity endpoint returns correct MachineIdentifier
- [x] LAN access confirmed
- [x] Server shows as "owned" at https://app.plex.tv
- [x] Libraries show existing content
- [x] Playback works (direct play and transcode)

### Phase 6: Clean Up

- [x] Commit compose.yaml and migration docs to podhaus repo
- [ ] Verify the documentary library path — one entry uses `/Volumes/Macintosh HD/Users/Shared/Pouch/Documentary Series` which won't resolve inside the container. Needs updating in Plex library settings.

## Post-Reinstall Recovery

After a clean macOS reinstall, the Plex data remains on the NAS. To restore:

1. Install OrbStack
2. Clone podhaus repo
3. Start the containers: `cd ~/repos/podhaus/plex && docker compose up -d`
4. Docker creates the NFS volumes and mounts directly from the VM — no host NFS setup needed for Plex

macOS autofs mounts (`/etc/auto_nfs`) are still needed for Finder access and other tools — see [NFS.md](NFS.md).

## Health and Recovery

### Sleep/wake resilience

A healthcheck verifies Plex API, media mount, and config mount every 30s. If NFS drops after sleep:

1. Linux NFS client auto-reconnects (NFSv4.1 session recovery) — healthcheck passes transparently
2. If reconnection fails, 3 consecutive healthcheck failures mark the container unhealthy
3. The `autoheal` container restarts Plex — Docker remounts NFS volumes with fresh handles

### Database backup and auto-recovery

The `plex-backup` sidecar runs daily:

1. Takes a snapshot via `sqlite3 .backup` (consistent, safe while Plex is running)
2. Runs `PRAGMA integrity_check` on the snapshot
3. If valid, promotes to `backup.db` on Pouch (different NAS volume from the live database on Jump)
4. If integrity check fails twice, the live database is corrupt — restores from last good `backup.db` and restarts Plex

Manual recovery: `docker compose stop plex`, copy `backup.db` over the live database, `docker compose start plex`. See `backup.sh` for details.

### Known risks

**SQLite on NFS:** The 44GB Plex database on Jump (NFS) has a small corruption risk on unclean shutdown. NFSv4.1 locking is adequate for single-writer, but crash recovery depends on NFS write ordering. The daily verified backup limits worst-case data loss to 24 hours of watch history and metadata changes.

**Database performance:** SQLite random I/O over NFS has higher latency than local SSD. If library browsing or search becomes sluggish, move config to local SSD by changing the `jump` volume definition and rsyncing the data.

## References

- [plexinc/pms-docker (official image)](https://github.com/plexinc/pms-docker)
- [Migrating Plex to Docker - Tanner's Tech](https://tcude.net/migrating-plex-to-docker/)
- [Migrate Plex From VM to Docker - Michael Gambold](https://www.michaelgambold.com/post/2026/01/migrate-plex-from-vm-to-docker/)
- [OrbStack Host Networking Docs](https://docs.orbstack.dev/docker/host-networking)
- [OrbStack Container Networking Docs](https://docs.orbstack.dev/docker/network)
- [Plex Hardware Transcoding Support](https://support.plex.tv/articles/115002178853-using-hardware-accelerated-streaming/)
- [pms-docker first-run script](https://github.com/plexinc/pms-docker/blob/master/root/etc/cont-init.d/40-plex-first-run)
