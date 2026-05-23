# 2026-05-23 — Pouch + Jump NFS mounts unrecovered after fenwick OOM reboot

**Status:** resolved. All action items completed 2026-05-23 same day.
**Severity:** medium. flood/unpackerr/plex/paperless degraded for ~1 hour post-reboot; backrest at risk of silently writing real backups to local disk on the next scheduled run (would have hit ~14 hours later).
**Trigger:** fenwick uvicorn OOM-killed bilby into hard-lock, requiring power-cycle reboot.

## Summary

A fenwick experiment OOMed bilby into an unrecoverable state, requiring a power-cycle reboot. On boot, `mnt-pouch.mount` failed with `Network is unreachable` (NFS tried before the network stack was up) and systemd left it permanently failed instead of retrying. `/mnt/jump` had never been in `/etc/fstab` at all — a documented gap that survived until a reboot exposed it. With both NAS mounts gone, container bind mounts silently resolved to empty local-disk stubs:

- **flood** kept its existing `(healthy)` status because its healthcheck checked `/proc/mounts` presence (which a Docker bind satisfies trivially) rather than checking that the source was the real NFS share. Torrents listed (rtorrent session state is on local NVMe), but every read of media files failed and torrent adds returned 500.
- **plex**, **paperless** entered restart loops (healthchecks correctly failed; autoheal restarted them every ~5 min into the same broken state).
- **unpackerr** spammed `stat /data/Movies: no such file or directory` every iteration with no healthcheck.
- **backrest** silently `restic-init`d a fresh empty repo on the local-disk stub at `/mnt/jump/backups/` (12 K of metadata, 0 data files yet). The first scheduled backup the next morning would have written real snapshots to bilby's local disk instead of the QNAP.

User reported flood as the visible symptom ("torrents show, seeding broken, add errored"); root-cause investigation surfaced the storage-layer collapse.

## Timeline

All times AWST (system tz). Reboot was a power-cycle, so monotonic clock reset; uptime referenced from boot at 13:18.

| Time | Event |
|---|---|
| ~earlier in day | fenwick experiment under development; uvicorn workers grow to multi-GB resident set. |
| pre-reboot | bilby hard-locks, swap exhausted; user power-cycles. |
| 13:18:51 | `mnt-pouch.mount` attempts NFS mount → `mount.nfs: Network is unreachable for 10.0.0.25:/Pouch`. Marked `failed`, never retried. `/mnt/jump` never attempts (no fstab entry). |
| 13:18:51 | flood, unpackerr, plex, paperless, backrest start; Docker bind-mounts onto empty stubs. flood's `/proc/mounts`-based healthcheck false-greens. plex/paperless healthchecks correctly fail; autoheal begins restart loop. backrest's restic open against `/mnt/jump/backups/` finds no repo, initializes a new one (config + key file on local disk). |
| 13:19:55 | fenwick uvicorn OOM-killed (7.04 GB anon-rss). 4 min after boot, same workload-class fault as pre-reboot. |
| 13:39:03 | User attempts to add a torrent via flood UI → `POST /api/torrents/add-files [500]` (logged). |
| 13:44:37 | Second OOM kills user-session `dbus-broker` + another uvicorn (2.36 GB). |
| ~13:52 | User asks Claude Code agent to investigate flood. Parallel agent (per user direction) begins working on fenwick container limits. |
| 14:08 | Investigation surfaces root cause: NFS mounts missing, healthcheck hole, backrest silent-init landmine. Report delivered. |
| 14:13 | User authorizes remediation. |
| 14:14 | Affected containers stopped. Ghost stubs wiped (`/mnt/pouch/plex-video-thumbnails`, `/mnt/jump/paperless`, `/mnt/jump/backups`). `chattr +i` tripwire applied to bare `/mnt/pouch` and `/mnt/jump`. |
| 14:15 | `/etc/fstab` updated: Jump entry added; both mounts converted to `x-systemd.automount`. `systemctl daemon-reload`; both automount units active. |
| 14:17 | First access triggers actual NFS mounts. Real content verified. Sentinel markers (`.podhaus-share-mounted`) dropped at every NFS bind-source path. |
| 14:20 | All affected stack compose files updated to use sentinel-marker healthchecks. Containers restarted; binds pick up NFS automatically. |
| 14:30+ | Docs cascade, postmortem, commit, `komodo-sync` redeploy. |

## Root cause

Two latent defects compounded:

1. **fstab boot-time NFS race.** `_netdev,nofail` lets boot continue if NFS is unreachable, but doesn't retry. The mount unit goes to `failed` state and stays there. On a normal-network boot this is invisible; on this reboot, network-online wasn't satisfied by the time mount tried, so the mount failed permanently. QNAP was reachable seconds later but nothing went back to check.

2. **`/mnt/jump` not in fstab at all.** Acknowledged in `docs/storage.html`'s "Mount-recovery gap" callout. It's a TOFU-mount that survives across reboots only as long as we don't reboot. We rebooted.

The downstream damage chain:

3. **Healthcheck idioms didn't prove "I bound the real NFS".** flood's `/proc/mounts` check satisfies on any bind, including binds onto bare stubs. plex/paperless used `ls` which works but couples healthcheck behavior to soft-NFS-stall semantics (the reason flood had moved off `ls` in 2026-04). unpackerr had no healthcheck.

4. **Bind-mount destinations had no tripwire.** Bare stub directories at `/mnt/pouch` and `/mnt/jump` were writable by root, so Docker happily auto-created subdirs underneath (Plex's `plex-video-thumbnails`, paperless's `documents`, backrest's restic-init at `backups/`). A future reader of those subdirs sees data — but it's local-disk data, not the QNAP. **The backrest case was the worst:** restic doesn't refuse to write to an unfamiliar repo path; it initializes a new one. The next scheduled backup would have populated it with real data.

## Impact

- **No data loss.** Backrest had written only the 12 K init metadata to its local-disk stub by the time we caught it; no actual snapshot data ever landed on the wrong disk. The real restic repo on QNAP was untouched (no client had written to it post-reboot).
- **User-visible service degradation:** flood add-torrent failures, plex/paperless restart loops. ~1 hour from reboot to remediation.
- **Silent risks closed:** backrest landmine averted; healthcheck pattern hardened across the fleet.

## Resolution

### Host-level (bilby, persistent)

- [x] **2026-05-23**: `/etc/fstab` rewritten — added Jump entry, both Pouch and Jump now use `x-systemd.automount`. Kernel autofs mounts on first access and silently retries on the next access if a prior mount failed. Survives QNAP reboots, network races, NFS server hiccups.
- [x] **2026-05-23**: `chattr +i` applied to bare `/mnt/pouch` and `/mnt/jump`. When NFS is unmounted, the underlying btrfs dirs are immutable, so any container bind whose source needs an auto-created subdir under them fails loudly at start. Mounting NFS over `+i` dirs is unaffected.
- [x] **2026-05-23**: Backup of pre-change fstab at `/etc/fstab.bak-2026-05-23` (host-only).

### Sentinel markers on the NFS shares (persistent, on QNAP)

- [x] **2026-05-23**: `.podhaus-share-mounted` files dropped at every NFS bind-source path used by any container:
    - `/mnt/pouch/.podhaus-share-mounted` — flood, unpackerr, plex (`/Users/Shared/Pouch`)
    - `/mnt/pouch/plex-video-thumbnails/.podhaus-share-mounted` — plex BIF
    - `/mnt/jump/paperless/.podhaus-share-mounted` — paperless media
    - `/mnt/jump/backups/.podhaus-share-mounted` — backrest repo
    - `/mnt/jump/paperless/documents/.podhaus-share-mounted` — backrest source bind
    - `/mnt/jump/.podhaus-share-mounted` — for any future bind at the Jump root

### Container healthchecks (in-repo, deployed via komodo-sync)

- [x] **2026-05-23**: `flood/compose.yaml` — healthcheck replaces `/proc/mounts " /data "` grep with `[ -e /data/.podhaus-share-mounted ]`. Keeps the `wget` HTTP probe and the local `/flood-db` `/proc/mounts` check.
- [x] **2026-05-23**: `plex/scripts/healthcheck.sh` — replaces `ls /Users/Shared/Pouch/Movies` and the BIF dir `ls` with `[ -e .../.podhaus-share-mounted ]` checks. `[ -e ]` is a `stat`, doesn't risk soft-NFS-stall.
- [x] **2026-05-23**: `unpackerr/compose.yaml` — first-ever healthcheck added: `test -e /data/.podhaus-share-mounted`. Autoheal label added.
- [x] **2026-05-23**: `paperless/compose.yaml` — healthcheck replaces `ls /usr/src/paperless/media` with sentinel check.
- [x] **2026-05-23**: `backup/bilby/compose.yaml` — bilby overlay extends shared healthcheck with `[ -e /repos/podhaus/.podhaus-share-mounted ]`. Future repo-on-wrong-disk regressions go red within a minute.
- [x] **2026-05-23**: `backup/bilby/stack.toml` — `file_paths` reversed to `["../compose.shared.yaml", "compose.yaml"]` so the bilby overlay actually wins on field conflicts. Docker compose's `-f` precedence is later-wins; the previous order (compose.yaml first) silently lost any field also defined by the shared file. The healthcheck override commit landed but did nothing until the file_paths flip — a half-fix that would have caught the next regression by failing to fail. Worth flagging as a learning.

### Documentation (in-repo)

- [x] **2026-05-23**: `docs/storage.html` — old "Mount-recovery gap" callout replaced with the automount + sentinel + tripwire description.
- [x] **2026-05-23**: `docs/runbooks/flood.html` — recovery chain documented (host-NFS-fix → autoheal restart → bind re-resolves).
- [x] **2026-05-23**: `docs/stack-conventions.html` — sentinel-marker healthcheck pattern added as a convention for any container binding an NFS share.
- [x] **2026-05-23**: `AGENTS.md` — postmortems list added with this entry; conventions doc pointer.
- [x] **2026-05-23**: `docs/postmortems/conventions.md` — postmortem-writing convention captured.
- [x] **2026-05-23**: `docs/postmortems/index.html` — index page created.

### Out of scope (not in this remediation)

- **fenwick OOM root-cause work** — owned by a parallel agent applying container memory limits. Tracked separately; not duplicated here. If fenwick continues to be the trigger for future bilby instability events that cascade like this one, those will get their own postmortems linking back here.
- **kangaroo backrest sentinel.** kangaroo's restic repo at `/share/CACHEDEV2_DATA/Jump/backups-kangaroo/` is accessed directly (not over NFS), so it has no bare-stub failure mode. The shared backrest healthcheck stays untouched on kangaroo; the bilby overlay's healthcheck override is bilby-only.

## What we learned

- **Docker compose `-f` precedence is later-wins.** When a service field is defined in both an included `compose.shared.yaml` and a per-host overlay, the LAST `-f` file in `file_paths` wins. The natural reading order ("host file first, then shared") is backwards from what you want for overrides. `backup/bilby/stack.toml`'s file_paths now reads `["../compose.shared.yaml", "compose.yaml"]` so the host overlay can override scalar fields. The original order silently dropped the bilby healthcheck override during this remediation — the fix-of-the-fix exposed the trap. Worth keeping in mind for any other multi-host service that grows host-specific overrides (`autoheal/`, `logging/`).

- **A bind mount's healthcheck must prove the source, not the bind.** `/proc/mounts` presence is satisfied by Docker's own bind entry regardless of the source state. Healthchecks need a positive signal that the source filesystem is the one we expect — a sentinel file on the share itself is the cheapest available primitive.

- **`nofail` without retry is a footgun.** It prevents boot from blocking but pretends nothing went wrong. Modern systemd-automount gives us both: no boot blocking *and* automatic retry on access. Use it for any non-essential network mount.

- **Bare mount-point dirs must be tripwires.** Containers will silently write to whatever directory they bind. `chattr +i` on an empty mountpoint makes "NFS down" loud at deploy time instead of silent at backup time.

- **Restic does not refuse unfamiliar empty paths.** It initializes a new repo. There's no built-in "make sure this repo is the one I think it is" check — that's on us. A repo-path sentinel is the simplest layered defence.

- **The "container is healthy" signal lies if the healthcheck is wrong.** Komodo, autoheal, Gatus, and the entire monitoring chain all believed flood was fine. The fix here lives in the healthcheck definition, not anywhere downstream — they were all reporting accurately on a bad input.

## Related

- `docs/storage.html` — NFS layout + automount/sentinel/tripwire defence
- `docs/stack-conventions.html` — sentinel-marker healthcheck pattern
- `docs/runbooks/flood.html` — flood-specific recovery flow
- `docs/postmortems/conventions.md` — how we write these
