# Pinelake Syncthing decision and migration

Syncthing currently runs natively through Homebrew and a user LaunchAgent. The
safe first state is to keep it native, back up its identity, and remove the
stale Alligator peer only after the Kangaroo recovery flip is complete.

Containerisation remains possible, but it needs a Pinelake-specific network
proof. Colima's host network is the Linux VM, not the macOS host or household
LAN, so bilby's `network_mode: host` design cannot be copied here.

## Current state to preserve

- State directory:
  `/Users/baxter/Library/Application Support/Syncthing/`
- Identity files: `cert.pem` and `key.pem`
- Index database: `index-v0.14.0.db/`
- Native GUI: `127.0.0.1:8384`
- Sync ports: TCP and UDP `22000`; local discovery UDP `21027`
- `default` folder: `/Users/baxter/Sync`, Send & Receive
- `pouch` folder: `/Volumes/TerraMaster`, Receive Only at the last audit

The certificate, key, config, and index database move as one unit. Losing the
identity forces every peer to approve a new device; losing the index triggers
a multi-terabyte rescan.

## Recommended first state: keep it native

1. Add the whole Syncthing state directory to Pinelake Backrest.
2. Verify Homebrew's LaunchAgent returns after login or reboot and that its
   user-session dependency is acceptable for an infrastructure host.
3. Complete the protected Kangaroo recovery sequence in
   [Kangaroo Pouch recovery](../kangaroo-pouch-recovery.md) before changing
   Pinelake's folder mode or peer list.
4. After both sides are current, remove the retired Alligator device from the
   folder memberships.
5. Add a machine-local rathole client for `127.0.0.1:8384`, then verify the
   Nathan-only Pomerium route before retiring cloudflared.

This path removes the current backup gap without combining it with an identity
and networking migration.

## Optional container migration

Do this only after the native state and restore path are proven.

### Staging proof

1. Pause Syncthing and take a second snapshot of the entire state directory.
2. Copy that snapshot to a staging path. Never point the first experimental
   container at the only live copy.
3. Use an image version compatible with the current database. Record whether
   it upgrades the database before considering rollback safe.
4. Preserve the in-container paths `/Users/baxter/Sync` and
   `/Volumes/TerraMaster`; the existing config uses those absolute paths.
5. Run as the UID/GID that can access both virtiofs mounts.
6. Publish the GUI only to macOS loopback, for example
   `127.0.0.1:8384:8384`, for the machine-local rathole client.
7. Explicitly publish TCP and UDP `22000` and UDP `21027`, then verify how
   Colima forwards them to the household LAN. Do not assume multicast discovery
   crosses the VM boundary.
8. Confirm the staged container reports the same device ID before allowing any
   folder to resume.

If local discovery cannot cross Colima reliably, choose between configured
static peer addresses, global discovery, or keeping Syncthing native. Do not
broaden ports or add a second overlay merely to make the container design fit.

### Cutover gate

- Device ID is unchanged in the staged container.
- All live peers can connect through the intended published ports.
- The GUI remains reachable at `sync.pinelake.haus` through Numbat and
  Pomerium.
- No full-folder rescan starts.
- Rollback to the installed native version has been tested against a copied
  database.

Only then stop the native LaunchAgent, point the container at the live state
directory, resume folders, and soak for 24 hours before uninstalling the
native package. Keep the LaunchAgent and pre-cutover snapshot until the soak is
complete.

## Verification

For the recommended native state:

- Backrest snapshots the identity and index, and the off-site mirror contains
  the repository objects.
- The device ID matches the pre-backup capture.
- All expected peers connect and no unexpected deletions appear.
- `sync.pinelake.haus` serves the GUI through Pomerium.

For a later container state, add explicit macOS-loopback, LAN TCP/UDP, peer
discovery, identity, rescan, and rollback checks to the implementation plan.
