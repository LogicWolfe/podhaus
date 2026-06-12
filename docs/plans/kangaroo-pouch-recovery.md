# Kangaroo Pouch outage — recovery status & open issues

**Status:** In progress · last updated 2026-06-12

This is the working handoff doc for the kangaroo Pouch RAID failure and its
recovery. It captures the summary, what's already resolved, and every known
open issue. When the recovery completes, fold the resulting-state bits into
the relevant `docs/` pages, write the postmortem, and delete this plan.

---

## Summary

A power outage (and a subsequent rebuild attempt) caused **kangaroo**'s Pouch
RAID5 (`md1`, originally 5×8TB) to **double-fault**, rendering the ~28TB media
volume unrecoverable as a redundant array. The bulk of Pouch (~20TB of
Anime / Movies / Comics / etc.) was **never backed up — accepted loss**.

Recovery (≈ 2026-06-05 → 2026-06-12): priority data was rescued off the
degraded array, the array was **wiped and rebuilt clean** as a fresh **4-disk
RAID5 static volume** (`[4/4]`, redundant, ~21.8 TB), the 10GbE link was fixed
and cut over, and services are being restored. **Plex is back up and healthy.**
**Kids/TV is restoring** from a USB backup. **All of kangaroo's container
stacks remain down** — Container Station itself was on the wiped volume and
needs reinstalling, which is also the moment to fix the backup-placement gap
this outage exposed.

---

## Resolved

- **Priority data rescued** before the wipe:
  - Photos ("Other Photos Library") → OneDrive (`onedrive:Recovered/`) + Jump;
    Family Photos already covered by Mylio (`onedrive:Apps/Mylio`).
  - `sky` (incl. sensitive data) → OneDrive.
  - **Kids/TV** (8493 files / 2.9 TB) → bilby USB drive (`/mnt/usb4t`).
  - Gmail exports (~52 GB) → Jump (`/share/CACHEDEV2_DATA/recovered/gmail/`).
- **Disks validated** (full `badblocks` write+read): sdc/sdd/sde/sdf clean;
  **sdd rehabbed** (8 pending → 0); **sdg (bay 1) = dead recycler**
  (81896 pending) — pulled.
- **New array built:** 4-disk RAID5 **static volume** (sdd/sdc/sdf/sde =
  bays 2/3/4/5), `[4/4] [UUUU]`, ~21.8 TB, via the QTS GUI. Resync complete.
- **UPS** (APC BX950MI-AZ) armed via NUT/upsmon — graceful shutdown on low
  battery.
- **10GbE recovered + cut over:** kangaroo active on **.25 (10G)**, **.232 (1G)
  kept as a live spare**; both TF-managed (`unifi_client.kangaroo` +
  `kangaroo_10g`, with the `kangaroo_active_ip` cutover knob). bilby fstab
  Pouch/Jump → .25.
- **Pouch share + NFS export recreated;** bilby `/mnt/pouch` remounted cleanly
  on .25 (`daemon-reload` fixed a stale `.232` mount unit). Sentinel + perms
  verified.
- **Plex restored:** BIF thumbnails relocated **Pouch → Jump**
  (`/mnt/jump/plex-video-thumbnails`); healthcheck updated to validate the Jump
  mount. Committed `1ec7b5a`, pushed, verified healthy, identity
  (`machineIdentifier`) preserved.
- **`ssh.pod.haus`** browser-rendered SSH built during the incident (lets
  `op-unlock` be run from the iPad to unblock long unattended tasks).

---

## Open issues

### 1. Kids/TV restore (in flight)
rclone SFTP copy USB → Pouch. ~37% / ETA ~4–5h as of 2026-06-12 18:30
(log: `/home/nathan/kidstv-restore.log`, conf `/tmp/kangaroo-sftp.conf`).
- On completion: verify `find /mnt/pouch/Kids/TV -type f | wc -l` **== 8493**
  (USB source count), then trigger a Plex **"Kids TV"** library scan.
- Keep the USB backup (`/mnt/usb4t`) until verified.

### 1b. bilby NFS-bind containers stopped during the incident — ✅ restarted
flood (stopped at outage start 2026-06-05), paperless + backrest (stopped
during the .25 cutover window 2026-06-10) were `docker start`ed 2026-06-12
~21:15 AWST after verifying mounts + sentinels. **All three healthy.**
- ✅ **backrest** — nightly bilby backups resume (missed 2026-06-10 → -12;
  heartbeat greens after the next nightly run).
- ✅ **paperless** — fully recovered, media on Jump intact. Remaining: fix the
  stale `.podhaus-jump-mounted` sentinel name in the healthcheck *comment*
  in `paperless/compose.yaml` (test itself is correct) — fold into the prep
  commit.
- ✅ **flood** — restarted; rtorrent loaded its 269 surviving session entries
  against wiped `/data`. **User is handling the missing-torrent fallout in
  the UI.** "RAR Extraction" heartbeat stays red until the pipeline next
  runs.

### 2. kangaroo container stacks are DOWN (Container Station gone)
Container Station lived on the wiped Pouch volume → gone. Everything
kangaroo-resident is down: **syncthing, kangaroo-backup (backrest), kangaroo
Periphery, kangaroo-logging, kangaroo-autoheal**. Rebuild requires reinstalling
Container Station (see #3), regenerating Periphery keys (#4), then redeploying.

### 3. Backup-placement architecture fix (the gap this outage exposed)
**Root cause:** kangaroo container state lived on **CACHEDEV1 (Pouch,
unbacked)** because Container Station defaulted there — it was only rescued by
backrest's cross-volume copy to the restic repo on **Jump (CACHEDEV2)** +
OneDrive. The intended model was "state lives on Jump, backed up." It didn't;
it lived on Pouch and was *copied* to Jump.

**Recoverable from restic** (`/share/CACHEDEV2_DATA/Jump/backups-kangaroo` →
`onedrive:Backups/podhaus-kangaroo-restic`): Syncthing identity + folder config,
Periphery `etc-komodo` config.

**Fix (at rebuild):**
- a. Reinstall Container Station targeting **CACHEDEV2 / Jump** so state lives
  natively on the backed-up volume.
- b. Sweep all kangaroo compose binds `CACHEDEV1_DATA/Container/…` →
  `CACHEDEV2_DATA/…/Container/…`: `syncthing/`, `kangaroo/periphery/`,
  `backup/kangaroo/`, `logging/kangaroo/`.
- c. Widen backrest's source mount `komodo-periphery/etc-komodo` → parent
  `komodo-periphery/` so the keys are captured.
- d. Fix the misleading "Backed up by kangaroo/backrest" comment in
  `syncthing/compose.yaml`; codify the rule in `docs/storage.html`
  (*kangaroo container state → CACHEDEV2/Jump; Pouch = unbacked bulk media +
  Syncthing's synced data only*).

### 4. kangaroo Periphery identity — ✅ no regeneration needed
kangaroo's copy of the privkey was wiped, but the **original
`kangaroo-periphery.key` is still on bilby** at `/opt/komodo/keys/` (verified
2026-06-12) — `kangaroo_bootstrap` SCPs it from there on every run. Core
already trusts the matching pubkey. Re-running bootstrap restores Periphery
identity as-is; no keygen, no `compose.env` change, no Core restart.

### 5. Syncthing rebuild — pinelake cascade-safety + recovery
Syncthing replicated a **whitelisted subset of movie/TV subdirs** (via a
`!keep … **`-ignore-rest `.stignore`) to **pinelake** (father's off-site copy).
That subset is **intact on pinelake = a recovery source**. The `.stignore`
whitelist (lived on Pouch) is lost, but its contents == what pinelake holds —
regenerate it from a pinelake listing during re-pair. **Decision (2026-06-12):
`.stignore` stays out of the repo** — it describes exactly the data it lives
beside, so losing it alongside that data costs nothing; no config-as-code
carve-in needed.

**⚠ Cascade risk at rebuild:** do **not** restore the old Syncthing identity +
folder config and let it reconnect to pinelake against an empty/partial Pouch —
that propagates deletes to pinelake. Safe path:
- Fresh device ID (won't auto-connect — user re-pairs manually on pinelake +
  other devices).
- kangaroo folder = **Receive Only** so data flows pinelake → kangaroo (pulls
  the titles back), never the empty side outward.
- ✅ **pinelake is already Send Only** (confirmed 2026-06-12; user has access)
  — cascade risk fully defused, no coordination needed.
- Switch to Send & Receive only after Pouch is fully restored + verified.

pinelake currently sees kangaroo as **offline** (disconnection ≠ deletion); its
copy is untouched and safe.

### 6. Array redundancy / capacity / aging fleet
Current: **4-disk RAID5 `[4/4]`**, ~21.8 TB usable (was 5-disk ~29 TB).
bay 1 / sdg pulled (dead recycler).
- Bay-1 replacement → 5-disk expansion: **deferred until the array fills up**
  (decision 2026-06-12). Array is redundant as-is.
- **All drives are old** (4.3–6.9 yr, 37k–61k hrs) — rotation/replacement
  planning warranted.

### 7. Scrub + UPS finalization
- ✅ **Scrub:** monthly, first Sunday 00:00; priority flipped to **Service
  First** (done 2026-06-12).
- **UPS:** armed; the minutes-based shutdown settings weren't ideal — possible
  minor tuning.

### 8. Plex trash cleanup (user-driven, later)
Goal: empty Plex trash to clear the lost (missing) media **while preserving
watch state**. Mechanics verified from the DB:
- Watch state lives in `metadata_item_settings`, keyed by `(account_id, guid)`,
  **not** FK'd to items and with **no delete trigger** → it survives trash and
  **reconnects on re-add by GUID**.
- **PRESERVED** for online-agent libraries (`tv.plex.agents.*` / `plex://`
  GUIDs = every library *except* Sports + Kids Video).
- **LOST** for the two `com.plexapp.agents.none` libraries (Sports, Kids Video —
  volatile local-hash GUIDs).
- Auto-trash is **OFF**, so missing items just grey out (no deletion) until you
  manually empty trash. **No urgency.** DB (14,687 watched items) is on bilby
  local NVMe + Plex nightly backups.

### 9. Recovery-staging cleanup
- `/share/CACHEDEV2_DATA/recovered/` on Jump holds gmail (~52 GB), photos, sky
  copies — rescue staging. Photos + sky are also on OneDrive. Decide a final
  home / clean up the duplicates.
- USB drive `/mnt/usb4t` = Kids/TV source; keep until the restore is verified.

### 10. Monitoring — complete red inventory (verified 2026-06-12)
11 of 25 gatus endpoints red; every one maps to a known cause above, no
surprises hiding:
- **Paperless, Flood (Torrent), Backrest (bilby)** + heartbeats **Backrest
  Nightly, RAR Extraction** → the stopped bilby containers (#1b).
- **Kangaroo Periphery / Backrest (kangaroo) / Syncthing (via Komodo),
  Kangaroo Log Ingest (staleness)** + heartbeat **Backrest Kangaroo
  Nightly** → kangaroo stacks down (#2).
- **Komodo Alerts** → exactly 1 unresolved CRITICAL alert (kangaroo
  Periphery unreachable); auto-clears with #2.
- The "Kangaroo (NAS)" probe targets **.232** (the spare) and is green —
  update to .25 so it watches the active link (config edit + deploy). Minor.

---

## Reference (for a fresh session)

- **op-unlock SSH agent:** socket `/run/user/1000/op-unlock/agent.sock`,
  ~16h TTL (expires often — the recurring blocker; renew via `op-unlock`,
  reachable from iPad via `ssh.pod.haus`). Prefix git/ssh with
  `SSH_AUTH_SOCK=<sock> GIT_SSH_COMMAND="ssh -o IdentityAgent=<sock>"`.
- **kangaroo:** `admin@10.0.0.25` (10G active), `10.0.0.232` (1G spare).
  QNAP quirks: `docker` not in admin PATH; no `nohup`/`timeout` (use `setsid`
  + full PATH `/usr/bin:/bin:/sbin:/usr/sbin`).
- **Arrays:** `md1` (Pouch) = RAID5 `[4/4]` sdd/sdc/sdf/sde (roles 0–3), static
  ext4, `/share/CACHEDEV1_DATA/Pouch`. `md2` (Jump) = RAID1,
  `/share/CACHEDEV2_DATA`. **Never touch** QTS system arrays
  (md9/md13/md256/md322) or md2.
- **restic repo:** `/share/CACHEDEV2_DATA/Jump/backups-kangaroo` →
  `onedrive:Backups/podhaus-kangaroo-restic`. Plans: `syncthing`,
  `komodo-periphery`, `backrest-state`.
- **bilby mounts:** `/mnt/pouch` (`10.0.0.25:/Pouch`), `/mnt/jump`
  (`10.0.0.25:/Jump`) — NFSv4 soft automount; sentinel `.podhaus-share-mounted`
  at each bind root.
- **Plex:** thumbnails `/mnt/jump/plex-video-thumbnails` (empty — BIFs
  regenerate on the scheduled task), media `/mnt/pouch`, DB on bilby
  `/var/lib/plex-local`.

**Related:** `docs/postmortems/2026-05-30-power-outage-nfs-recovery.md` (the
bilby-side NFS automount fix from the same outage window),
`docs/postmortems/2026-05-23-pouch-jump-mount-failure.md`.
