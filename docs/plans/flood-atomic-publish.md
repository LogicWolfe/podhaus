# Flood → Plex atomic publish (hardlink model)

**Status:** Planning only · last updated 2026-06-22

Nothing has been built yet. This captures the root cause, the
architecture decision, the component-by-component design, the open
decisions, and the validation steps. When it ships, fold the
resulting-state bits into [`runbooks/flood.html`](../runbooks/flood.html)
(and a line into [`runbooks/plex.html`](../runbooks/plex.html)) and
delete this plan.

---

## Problem

There is no Sonarr/Radarr. Torrents are added in Flood with the
per-torrent destination set **directly into the Plex library tree**
(`/data/{TV,Movies,Kids}` = `/mnt/pouch` = Plex's
`/Users/Shared/Pouch`). rtorrent writes pieces in place at the final
library path, so there is no atomic boundary anywhere between
"downloading" and "in the library." Plex auto-scans on change, indexes
the partial file, and runs analysis (chapter/video thumbnails, intro +
credit detection) against a truncated file. The maintenance pass only
re-runs analysis for items *missing* it, so a bad marker or short
thumbnail index from a partial is considered done and never redone.

Two race windows, behaving differently:

- **Non-RAR (the common case — one or more loose `.mkv` in a folder or
  the root):** the partial `.mkv` sits at its final library path for the
  entire download. Large window.
- **RAR:** during download only `.rar`/`.rNN` pieces exist (Plex ignores
  those), but `bsdtar` in `rtorrent-extract.sh` extracts **to the final
  filename, in place**, on finish — so a partial `.mkv` exists at the
  real path for the extraction duration. Smaller window, still real.

Goal: a clean `Movies`/`TV` library that only ever contains complete
files, with **file-at-a-time delivery** — mark episode 1 high priority
in a season-pack torrent and get it the moment it lands, not when the
whole season finishes.

---

## Architecture decision: separate download dir + hardlink publish

Stop downloading into the library. This is the Sonarr hardlink model.

- **Download dir** = `/data/torrents` (already rtorrent's default
  `directory`, already outside every Plex library — `/data/torrents` is
  a sibling of `/data/{TV,Movies,Kids}`, not inside them, so Plex never
  scans it). rtorrent's working tree lives here and holds the messy
  reality: the release folder, `.nfo`, `sample/`, `.rar` pieces.
- **Library** = a curated, media-only **hardlink farm** under
  `/data/{TV,Movies}`. The publish step links only the media files we
  want, into the names/structure we want. Scene junk never enters the
  library because we never link it — so the library ends up *cleaner*
  than it is today.
- The path you type at add-time is reinterpreted as the **publish
  target**, not the download dir.

**Why hardlink, not move:** a completed file is still a live torrent
member; moving it out from under rtorrent breaks the seed. A hardlink
publishes it while rtorrent keeps seeding the original from
`/data/torrents`.

**Hardlink semantics that make this safe (no swap needed):** a file's
bytes live in an inode; a filename is just a directory entry pointing at
it. All links to an inode are peers — there is no "true source." One
copy on disk regardless of link count (`df` sees one copy). When the
torrent side is deleted, the library link keeps the inode alive
(refcount). So the direction of linking is irrelevant and no
move-and-relink dance is required.

This supersedes the earlier in-place `.incoming` dot-prefix idea — a
dedicated download dir is cleaner and reuses the existing default.

---

## Components

### 1. `event.download.inserted_new` — redirect download, capture target

At insert (before any data lands), the human's typed destination is in
`d.directory`. The hook:

- stashes it: `d.custom.set = publishdir, <d.directory>`
- redirects the download: `d.directory.set = /data/torrents/<d.hash>`
- `d.save_full_session` so both persist across restart.

`<d.hash>` subdir gives per-torrent isolation (clean per-torrent
cleanup, no name collisions). If no target was typed (directory left at
the `/data/torrents` default), there is no publish target — the file
stays in `/data/torrents`, unpublished. Acceptable degenerate case.

### 2. Per-file publish tick — `flood-publish.sh` (ofelia ~1–2 min)

The file-at-a-time delivery. Same ofelia-tick pattern as
`pinelake-stignore`, so no new always-on daemon.

- `d.multicall2` over the torrent view → per torrent: hash, `base_path`,
  `publishdir` custom field.
- `f.multicall` → `f.completed_chunks=`, `f.size_chunks=`, `f.path=`.
- For each file where **`completed_chunks == size_chunks`**, is a media
  extension, and isn't already published → **hardlink** into
  `publishdir/<relpath-under-base>`.
- **Idempotent via inode equality** (`stat -c %i` src vs dst) —
  self-healing, no marker bookkeeping.

A file is genuinely done exactly when `completed_chunks == size_chunks`:
`size_chunks` includes the partial boundary chunks a file shares with
its neighbors, so equality means every byte is downloaded and
hash-verified on disk — never a false positive. (To *finish* E01,
rtorrent must fetch the boundary chunk it shares with E02, dragging in a
few KB of E02. Harmless.)

This naturally only touches non-RAR torrents: a RAR torrent's `f.path`
lists `.rar` pieces (filtered out by the media-extension check), and the
extracted `.mkv` is not a torrent member so it never appears in
`f.multicall`. Single-mkv and per-episode torrents fall out for free.

**Tooling — a deliberate break from the pinelake no-XMLRPC pattern.**
Pinelake reads session files because tag state is *settled*. Per-file
completion is *live* state; reading it from `.libtorrent_resume` would
mean reimplementing chunk-boundary math in shell against the bitfield +
piece length + file sizes — fragile, and rtorrent already computes it.
So this queries rtorrent directly over the existing `/tmp/rtorrent.sock`
SCGI socket via a vendored `xmlrpc2scgi.py`. Cost: add `python3` to
`flood/Dockerfile` (one apk layer; Python is already a repo dependency
via `init-tools`).

### 3. `event.download.finished` — extract then publish

Ordered after the existing extract hook:

- extract RARs (existing `rtorrent-extract.sh`, **fixed for
  multi-archive** — see #4), now under `/data/torrents`.
- run the publish pass immediately, so the last files and any extracted
  output land without waiting for the next tick.

Non-RAR files are mostly already published by ticks; finish reconciles
the tail. The RAR-extracted `.mkv` isn't a torrent member, so the tick
never sees it — the finish-hook publish is what links it into the
library.

### 4. Multi-archive RAR fix

`rtorrent-extract.sh` currently extracts only the *first* archive it
finds (`find … | head -n 1`). A RAR season-pack torrent with multiple
per-episode release subfolders extracts only E01, drops its marker, and
exits 0 — the rest are silently never extracted, and the
`_unpackerred.*` marker fools `rar-backlog.sh` into thinking the folder
is handled. Fix: extract **every distinct archive set** under
`base_path` and publish each. (Pre-existing bug, folded in here because
the publish pass needs "all archives extracted," not "one.")

### 5. Cleanup + safety — monitor, not guard

Deleting the torrent side is safe by construction: removing a name only
decrements the inode refcount; the library link keeps the data.

- **Delete:** native Flood **Remove and delete data**, no delete-time
  guard. This is deliberate — it preserves the "I picked the wrong
  torrent, nuke it with data before it finished" workflow. A
  wrong-torrent file is link-count 1 (never published) → correctly
  deleted. A finished+published file's library link survives via
  refcount.
- `rtorrent-cleanup.sh` is **deleted entirely**, and its
  `event.download.erased` hook is removed from `rtorrent.rc`. Its whole
  reason — selectively stripping RAR cruft while preserving the
  extracted video *in the library folder* — only existed in the
  download-in-library model. In the hardlink model the
  `/data/torrents/<hash>` tree is disposable working state, so cleanup
  is just native Flood **Remove and delete data** deleting the whole
  tree. The "never delete the only copy" safety it provided moves to the
  publish-side monitor below. (Accepted trade: hitting **Remove**
  *without* delete-data now leaves an orphan working-tree folder in
  `/data/torrents` — reclaimed manually, not worth a helper for.)
- **Safety lives on the publish side, not on deletes.** The only way
  "delete data" loses something wanted is: a torrent finished, its media
  *should* have published but silently didn't, and you delete it
  assuming the library has it. Fix that with observability, not by
  blocking deletes: extend the daily `rar-backlog` heartbeat to flag
  "completed torrent with media not yet hardlinked into the library" →
  Gatus alert *before* you'd ever delete.

---

## Plex change detection — reliable here, with a constraint

No explicit `Plex Media Scanner --scan` call is needed. flood is
bilby-resident and Plex runs `network_mode: host` on bilby, both binding
the *same* `/mnt/pouch` client mount. The hardlink (`link()`) goes
through bilby's local VFS → fsnotify fires → Plex's inotify watch on the
same inodes gets `IN_CREATE`/`IN_MOVED_TO` and runs its partial scan.

**Constraint:** this holds only while flood and Plex co-reside on bilby.
The inotify-over-NFS limitation is strictly about *cross-client*
changes; if flood ever moved to kangaroo, the publish would become a
cross-client change, inotify would not fire, and an explicit scanner
trigger would be required.

---

## Files touched

- `flood/conf/rtorrent.rc` — `inserted_new` redirect + capture;
  finish-hook ordering.
- `flood/Dockerfile` — add `python3`.
- `flood/scripts/xmlrpc2scgi.py` — vendored SCGI client (new).
- `flood/scripts/flood-publish.sh` — the publish tick + the shared
  hardlink helper (new).
- `flood/scripts/rtorrent-extract.sh` — multi-archive fix; path root →
  `/data/torrents`.
- `flood/scripts/rtorrent-cleanup.sh` — **delete**; remove its
  `event.download.erased` hook from `rtorrent.rc`.
- `flood/scripts/rar-backlog.sh` — path root → `/data/torrents`; add the
  unpublished-completed-media check.
- `flood/scripts/pinelake-stignore.sh` — emit the **publish-target**
  path, not `base_path` (which is now under `/data/torrents` and not
  what syncthing serves).
- `flood/compose.yaml` — ofelia label for the publish tick.

---

## Open decisions

- **Publish path shape:** `target/<torrent-folder>/E01.mkv` (preserve
  the release-folder layout) vs flatten to `target/E01.mkv`. Lean
  preserve — Plex handles both and it matches current behavior.
- **Media filter + samples:** which extensions count; skip `*sample*`
  ourselves vs rely on Plex's built-in sample filter.
- **Tick interval:** 1 min (snappier) vs 2 min (lighter). Either fits
  the minutes-not-seconds goal.
- **Existing in-library content:** today's downloads already live in
  `/data/{TV,Movies,Kids}` as the torrent `base_path` (rtorrent seeding
  from there). The new model doesn't require moving them — grandfather
  them as-is and apply the model only to new torrents.

---

## Validation

- `ln` across the export (`/data/torrents` → `/data/TV`) on the live
  Pouch mount — confirm same-filesystem hardlink succeeds NFS
  server-side.
- Multi-file non-RAR torrent with E01 set high priority → E01 hardlinks
  into the library and appears in Plex while the rest is still
  downloading.
- RAR pack with multiple episode subfolders → all episodes extracted and
  published.
- Remove-with-data on a wrong torrent pre-publish → data gone
  (link-count 1). Remove-with-data on a finished, published torrent →
  library copy survives.
- Gatus unpublished-completed-media alert fires when a publish is
  artificially skipped.
