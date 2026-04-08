# Plex Containerization Plan

## Current State

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

### Critical Identifiers (must be preserved)

- `MachineIdentifier`: `9e4361f9-cdb9-4157-8bf9-f5b154d43ba9`
- `ProcessedMachineIdentifier`: `35bc90b6511a4a3dd245b5d4f2f4896bb0bb4e49`

## Design Decisions

### Config lives in podhaus repo

All container config lives in `plex/` within `~/repos/podhaus`, following the existing pattern of `<service>/compose.yaml`. No `stack.toml` is created — Komodo's ResourceSync auto-discovers any directory with a `stack.toml`, and we don't want Plex picked up yet. Values are hardcoded in the compose file (matching the pattern of other compose files like flood), not interpolated via env vars.

### Config/database on Jump, media on Pouch

Two NAS mounts with very different performance profiles:

- **`/Users/Shared/Jump`** (NFS, 382GB, fast) — Plex config, database (44GB), metadata. This is where container state lives.
- **`/Users/Shared/Pouch`** (NFS, 29TB, bulk) — Media files only.

The 44GB SQLite database lives on Jump. SQLite random IO latency over NFS will be higher than local SSD (~0.5-1ms vs ~0.01ms per round-trip), but Jump's smaller dedicated volume should have better IOPs than the 29TB media array. If library browsing or search becomes sluggish, config can be moved to local SSD later.

### NFS mount on macOS, not inside Docker

The NFS mount is managed on the macOS side at `/Users/Shared/Pouch`. The Docker container bind-mounts this macOS path. This means:
- Other containers can trigger on inotify events from the same mount
- Mount lifecycle is managed by macOS, not Docker
- The mount path inside the container matches the host path, so all existing library paths in the Plex database remain valid with zero reconfiguration

### Identity mount for zero library reconfiguration

The media volume is mounted as `/Users/Shared/Pouch:/Users/Shared/Pouch` — the container path matches the host path. Since all library paths in the Plex database are absolute paths under `/Users/Shared/Pouch`, they remain valid without any edits.

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
│   ├── compose.yaml     # Docker Compose definition
│   └── MIGRATION.md     # This file
├── flood/
│   ├── compose.yaml
│   └── stack.toml
├── home-assistant/
│   └── ...
└── ...
```

No `stack.toml` — Komodo's ResourceSync auto-discovers and deploys any directory with a `stack.toml`. Without one, Plex stays invisible to Komodo until we're ready to migrate it.

No `.env` file or `${VAR}` interpolation — following the pattern of other compose files in the repo (e.g. flood hardcodes `/mnt/NFSPouch:/data`), paths are written directly. The `MEDIA_DIR` variable in `variables.toml` is vestigial and unused by any current compose file.

## Docker Compose (`plex/compose.yaml`)

```yaml
services:
  plex:
    container_name: plex
    image: plexinc/pms-docker:latest
    restart: unless-stopped
    network_mode: host
    environment:
      TZ: Australia/Perth
      PLEX_UID: "501"
      PLEX_GID: "20"
      CHANGE_CONFIG_DIR_OWNERSHIP: "false"
    volumes:
      - /Users/Shared/Jump/plex:/config
      - /Users/Shared/Pouch:/Users/Shared/Pouch
    tmpfs:
      - /transcode:size=4g
```

When it's time to bring this into Komodo, add a `stack.toml`, adjust paths for Linux, and add UID/GID appropriate for the Linux host.

### Bridge Mode Fallback (if host mode doesn't expose to LAN)

Replace `network_mode: host` with explicit port mapping and `dockernet`:

```yaml
    ports:
      - "32400:32400"
      - "1900:1900/udp"
      - "5353:5353/udp"
      - "8324:8324"
      - "32410:32410/udp"
      - "32412:32412/udp"
      - "32413:32413/udp"
      - "32414:32414/udp"
    networks:
      - dockernet

networks:
  dockernet:
    external: true
```

## Execution

### Phase 1: Prepare

- [ ] Ensure OrbStack is running and `docker ps` works
- [ ] Verify `/Users/Shared/Pouch` and `/Users/Shared/Jump` are NFS-mounted and accessible
- [ ] Create config directory on Jump:
  ```
  mkdir -p "/Users/Shared/Jump/plex/Library/Application Support"
  ```

### Phase 2: Bulk Copy (Plex still running, minimises downtime)

- [ ] Initial rsync of Plex data while Plex is still serving clients:
  ```
  rsync -avP \
    "/Users/nathan/Library/Application Support/Plex Media Server/" \
    "/Users/Shared/Jump/plex/Library/Application Support/Plex Media Server/"
  ```
  This will be inconsistent (database is live) but transfers the bulk of the 58GB.

### Phase 3: Cut Over (downtime starts)

- [ ] Disable Plex auto-start (remove from Login Items in System Settings)
- [ ] Stop Plex:
  ```
  killall "Plex Media Server"
  ```
- [ ] Confirm all Plex processes are gone:
  ```
  ps aux | grep -i plex | grep -v grep
  ```
- [ ] Final rsync (consistent, only diffs):
  ```
  rsync -avP --delete \
    "/Users/nathan/Library/Application Support/Plex Media Server/" \
    "/Users/Shared/Jump/plex/Library/Application Support/Plex Media Server/"
  ```
- [ ] Verify Preferences.xml is present and correct:
  ```
  grep MachineIdentifier "/Users/Shared/Jump/plex/Library/Application Support/Plex Media Server/Preferences.xml"
  ```
  Should contain `MachineIdentifier="9e4361f9-cdb9-4157-8bf9-f5b154d43ba9"`

### Phase 4: Start Container

- [ ] If no `PlexOnlineToken` in Preferences.xml, get a claim token from https://plex.tv/claim (expires in 4 minutes, no quotes around the value). Pass it as a one-shot env var:
  ```
  cd ~/repos/podhaus/plex && PLEX_CLAIM=claim-xxxx docker compose up -d
  ```
  The `pms-docker` image reads `PLEX_CLAIM` from the environment. No need to persist it anywhere — it's only used on first start to exchange for a permanent `PlexOnlineToken` written into Preferences.xml.
- [ ] If claim token isn't needed (existing token preserved), just start directly:
  ```
  cd ~/repos/podhaus/plex && docker compose up -d
  ```
- [ ] Check logs:
  ```
  docker logs -f plex
  ```

### Phase 5: Verify

- [ ] Web UI at `http://localhost:32400/web` — confirm server loads
- [ ] Check identity endpoint:
  ```
  curl -s http://localhost:32400/identity
  ```
  Should return the correct `MachineIdentifier`
- [ ] **LAN test**: from another device, access `http://10.0.0.119:32400/web`. If this fails, switch to bridge mode fallback.
- [ ] Confirm server shows as "owned" at https://app.plex.tv
- [ ] Test from a LAN client (phone, TV, etc.) — server should appear with the same name
- [ ] Verify all 11 libraries show existing content without re-scanning
- [ ] Test playback: direct play and transcoded content
- [ ] Verify Trakttv and Sub-Zero plugins are operational
- [ ] Check remote access: Settings > Remote Access
- [ ] Run "Empty Trash", "Clean Bundles", "Optimize Database" from Settings > Troubleshooting

### Phase 6: Clean Up

- [ ] No cleanup needed for claim token (passed as one-shot env var, not persisted)
- [ ] Verify the documentary library path — one entry uses `/Volumes/Macintosh HD/Users/Shared/Pouch/Documentary Series` which is a full-path variant. May need updating if it doesn't resolve inside the container.
- [ ] Keep the original data at `~/Library/Application Support/Plex Media Server/` as a rollback backup until confident
- [ ] Commit `plex/compose.yaml` and `plex/MIGRATION.md` to podhaus repo

## Rollback

If anything goes wrong:

1. `cd ~/repos/podhaus/plex && docker compose down`
2. Re-enable native Plex: open `/Applications/Plex Media Server.app`
3. Original data is untouched at `~/Library/Application Support/Plex Media Server/`

## Known Risks

### OrbStack LAN accessibility

OrbStack documentation is ambiguous about whether `--net=host` or `-p` port forwards are reachable from LAN devices (not just localhost). This must be verified in Phase 5 by testing from another device. If not reachable, the bridge mode fallback with explicit port mapping should work, or a lightweight socat/caddy reverse proxy on the Mac can forward traffic.

### Preferences.xml overwrite

The official `pms-docker` first-run script merges into an existing Preferences.xml rather than overwriting — but only if the file exists before the container starts. The rsync in Phase 3 ensures this. If the file does get clobbered, restore from the backup at `~/Library/Application Support/Plex Media Server/Preferences.xml`.

### NFS mount availability

If either NFS mount drops, the container loses access to config (Jump) or media (Pouch). The container's `restart: unless-stopped` policy will restart Plex if it crashes, but it won't fix a missing mount. Consider monitoring mount availability.

### Database performance on NFS

The 44GB SQLite database on Jump (NFS) will have higher latency than local SSD. Jump's dedicated smaller volume should have better IOPs than Pouch, but if library browsing or search becomes sluggish, move the config to local SSD by updating the compose volume path and rsyncing the data.

## References

- [plexinc/pms-docker (official image)](https://github.com/plexinc/pms-docker)
- [Migrating Plex to Docker - Tanner's Tech](https://tcude.net/migrating-plex-to-docker/)
- [Migrate Plex From VM to Docker - Michael Gambold](https://www.michaelgambold.com/post/2026/01/migrate-plex-from-vm-to-docker/)
- [OrbStack Host Networking Docs](https://docs.orbstack.dev/docker/host-networking)
- [OrbStack Container Networking Docs](https://docs.orbstack.dev/docker/network)
- [Plex Hardware Transcoding Support](https://support.plex.tv/articles/115002178853-using-hardware-accelerated-streaming/)
- [pms-docker first-run script](https://github.com/plexinc/pms-docker/blob/master/root/etc/cont-init.d/40-plex-first-run)
