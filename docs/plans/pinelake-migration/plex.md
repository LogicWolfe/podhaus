# Pinelake Plex decision and migration

Plex currently runs as the native Apple Silicon application on Pinelake. Do
not containerise or move it as a side effect of bringing the host under
Komodo. The safe first state is a managed Pinelake host with Plex still native
and backed up.

This is the highest-risk Pinelake decision because the current server has a
stable Plex identity, 22 GB of local state, absolute TerraMaster library paths,
and native VideoToolbox acceleration that a Linux container under Colima
cannot use.

## Current state to preserve

- Application state:
  `/Users/baxter/Library/Application Support/Plex Media Server/`
- macOS preferences and identity:
  `/Users/baxter/Library/Preferences/com.plexapp.plexmediaserver.plist`
- Machine identifier: `c9d75740-0fd3-4bba-9874-be61f5dc8d38`
- Friendly name: `Pine Lake`
- Media roots: absolute paths under `/Volumes/TerraMaster`
- Native listener: TCP `32400` on the Mac

Re-read all values from the live host before acting. The inventory is dated
2026-05-13 and is not authority for a cutover months later.

## Decision

Choose one path after the Pinelake platform foundation and backups are live.

### A. Keep Plex native on Pinelake (recommended first state)

This preserves hardware acceleration, macOS networking, discovery, the login
item, and the current data layout. Komodo manages the surrounding platform but
not Plex itself.

Required work:

1. Add the native Plex state to Pinelake Backrest. Mount containing
   directories, never the plist as a single-file bind. Either expose the
   Preferences directory read-only and select only the Plex plist in the plan,
   or copy the plist into a dedicated backup staging directory before the
   snapshot.
2. Back up the full Plex state initially. Decide later whether the 20 GB
   `Media/` tree and 1.4 GB `Metadata/` tree are worth excluding; both are
   regenerable but expensive to rebuild.
3. Record the machine identifier and token source in 1Password without
   changing the live token.
4. Verify the native login item returns after a real reboot.
5. Keep Plex remote access on Plex's own path. Add no Numbat browser route
   unless a concrete operator need appears.

### B. Containerise Plex on Pinelake

Treat this as a separate migration after path A has soaked. Colima is a Linux
VM, so `network_mode: host` means the VM network namespace, not the macOS host
or household LAN. The final compose must use proven Colima port forwarding and
must not copy bilby's `172.18.0.1` host-service pattern.

Before approving this path, prove all of the following against a copied state
tree while native Plex remains stopped or isolated:

- The chosen image's config root is correct. `plexinc/pms-docker` expects
  `/config/Library/Application Support/Plex Media Server/`; mounting the native
  `Plex Media Server` directory directly at `/config` is wrong.
- Published port `32400` is reachable from LAN clients and Plex's native
  remote-access path.
- Client discovery works, or the household accepts explicit server URLs.
- The plist-to-`Preferences.xml` translation retains the machine identifier,
  processed identifier, certificate UUID, friendly name, home membership, and
  online token.
- Library roots remain `/Volumes/TerraMaster/...` inside the container, so no
  database path rewrite is required.
- Real transcode history shows software-only encoding is acceptable. Colima
  does not expose macOS VideoToolbox to the Linux container.
- A copied database opens cleanly after a WAL checkpoint, and the container
  does not force a schema migration that breaks rollback to the installed
  native version.

Only after those proofs should this page gain a concrete compose and cutover
sequence. The init container must refuse to start Plex unless the rendered
`Preferences.xml` contains the expected machine identifier. Its template may
be a single-file bind because the init reads it once and exits; the long-lived
Plex service must use directory binds.

### C. Move Plex to bilby

This consolidates servers but moves roughly 6.5 TB across households and
requires library path changes or a new storage topology. It is the largest
blast radius and has no current operational need. Keep it as an option only if
Pinelake hardware or ownership is being retired.

## Backup and rollback gate

Before either B or C:

1. Stop Plex cleanly and checkpoint its SQLite WAL.
2. Take an off-host snapshot of the full application-support directory and
   plist.
3. Compare file counts and sample SHA-256 hashes.
4. Confirm the snapshot contains the current database, blobs database,
   `Preferences` material, `Metadata`, and `Media` trees.
5. Prove a restore into a separate directory before changing the live app.

The rollback for any experimental container cutover is to stop the container,
restore the pre-cutover state if it was mutated, and reopen the same native app
version. Do not roll an upgraded Plex database back into an older native
binary.

## Verification

For the recommended native state:

- Backrest completes a Plex snapshot and the off-site mirror contains it.
- The native app returns after reboot with the same machine identifier.
- All library sections and watch history remain present.
- LAN playback and at least one remote playback path work.
- A hardware-transcoded session still reports VideoToolbox when expected.

For a later container cutover, add identity, networking, discovery, direct
play, transcode, backup, and rollback checks before implementation begins.
