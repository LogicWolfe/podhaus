# Separate Flood and rTorrent on Bilby and Pinelake

## Goal and reason for the change

Keep all torrents, download state, destinations, tags, and media publishing working while replacing the deprecated combined image with independently maintained Flood and rTorrent containers. Failed uploads must leave an actionable server error in central logs.

Bilby currently runs Flood 4.14.2 and rTorrent 0.9.8. The combined image stopped receiving releases; current upstream releases are Flood 4.16.2 and rTorrent 0.16.24. Two failed three-file uploads returned HTTP 500 without retaining the underlying exception. Splitting containers solves the update constraint; it does not itself solve missing error logging or prove why those particular uploads failed.

The change adds one engine service and one private socket volume per host. It removes the combined process lifecycle and separates web UI updates from engine updates. Stop the migration if compatibility tests cannot preserve torrent state and publishing behavior; keep the current service running until that is resolved.

## Service responsibilities and persistent state

| Component | Result |
| --- | --- |
| Flood web UI | Build the current stable source with a small error-logging change maintained only in the private `LogicWolfe/flood` fork on `git.pod.haus`. No upstream pull request or public patch publication. Fetch the fork through a read-only BuildKit secret; credentials never enter image layers. Keep HTTP address, authentication, secret, settings database, and `/data` browser paths. Log exceptions and request route/status without torrent payloads, cookies, credentials, or request bodies. |
| rTorrent engine | Build current official stable source on Alpine because distro packaging trails current upstream. Install Python, PlexAPI, and libarchive used by existing hooks. Own the completion hooks and Ofelia jobs. Keep the existing session directory and `/data` mapping. |
| Private connection | Share a Docker named volume mounted at `/tmp` between engine and UI, retaining `/tmp/rtorrent.sock` for existing scripts. No network-exposed remote-control port. Both services run with the host's existing media user and group. Init owns the volume directory; engine recreates its socket on startup. |
| Startup and health | Existing init installs the modern engine configuration and prepares writable files/socket volume. Engine health proves remote-control response and real storage presence. Flood starts after engine health, and its own health proves HTTP and storage. Both remain supervised by autoheal. |
| Logs | Preserve the full structured Flood error record in Alloy. Engine info/warning/error output and existing job logs remain collected. Do not enable verbose peer/debug logging. |

This is a major process-boundary change, but keeps the existing HTTP and script interfaces. Keep the old shared Dockerfile/config operational until Pinelake is ready. A normal fleet push hashes the shared context and can recreate Pinelake even when its compose file is unchanged. For the Bilby trial only, copy the final Flood tree to Bilby's managed deploy tree, calculate all stack/build hashes using the canonical algorithm, and invoke only `DeployStack flood`. Do not run a global push, sync, or hash action during this trial. Verify running labels and baked hashes. An intervening unrelated push would replace the trial tree; detect and reapply before continuing. The final commit and normal fleet push converge both ready host configurations.

## Host-specific storage safeguards

| Host | State and media | Safeguards |
| --- | --- | --- |
| Bilby | `/var/lib/flood-db`; Pouch mounted at `/data`; UID 1000, GID 1001 | Retain the NFS sentinel and bounded health probes, including outage tolerance. Both processes retain the same paths and permissions. |
| Pinelake | `/Users/Shared/Podhaus/flood`; `/Volumes/TerraMaster/Torrents` mounted at `/data`; UID 501, GID 20 | Retain the pre-deploy mount gate, `create_host_path: false`, UUID sentinel `EAED18A9-74C7-4163-ACB4-406B2226FDC6`, host networking, and native Plex path translation. Socket volume stays inside OrbStack, never on APFS. Validate hardlinks on the real external volume. |

Do not move or recursively change ownership of media. Preserve download state and custom fields, including publishing destinations and completion markers. Only one engine may access a session directory at a time.

## Verification before deployment

- Exercise a private, trackerless synthetic torrent through the real authenticated Flood HTTP API against isolated temporary engine state. Confirm a three-file upload succeeds and destinations/tags reach the engine. Confirm new downloads redirect into `/data/torrents`, preserving the requested publishing destination.
- Complete a small local fixture and confirm the publishing hook creates a hardlink with the same inode and content. Verify the engine supports every RPC method used by Flood and the media scripts.
- Submit an invalid torrent and require an HTTP failure plus a structured server error containing the cause. First establish that the existing handler fails the logging assertion, then verify the patch passes it. Send unique cookie, authorization and payload canaries and assert their absence in the complete stored error; assert route and status are present. Check central collection retains the exception, with correct severity and timestamp.
- Stop/restart the actual containers independently, using the configured signal and grace period. Change an incomplete torrent's progress and custom fields after its last session save; verify resume state survives and the UI reconnects.
- Validate Compose rendering, content-hash/environment lints, existing relevant tests, and the full repository check suite. Verify storage probes fail against a missing sentinel in isolation; never unmount live media for a test.

## Deployment, review, and rollback

1. On each host separately, record live torrent hashes, names, state, progress, paths, tags, settings, and publishing custom fields. Save session state, stop the old engine cleanly, and take a temporary consistent copy of the small state directory. Retag the old image before any build overwrites its local tag; do not duplicate media. Run the new UI and engine against a writable copy of the complete saved state, with live media read-only, no network and completion hooks/jobs disabled. Compare the copied inventory and settings before allowing live-state access.
2. Deploy Bilby through the scoped Komodo trial described above. Compare all recorded torrents and custom fields; exercise a synthetic upload, engine reconnection, job execution, and central error collection. Confirm the scheduler executes each job exactly once from the engine container.
3. After Bilby is working, run the requested independent deep review for correctness, simplicity, and consistency with Podhaus conventions. Resolve findings and rerun affected checks before proceeding.
4. Repeat the stopped backup and copied-state compatibility check on Pinelake. Then apply the verified arrangement through its linked-repository stack and the ordinary final fleet push. Verify OrbStack architecture, external-volume identity, permissions, hardlinks, native Plex translation, and existing torrents before declaring success.
5. On a failed migration, stop both new services before restoring the saved state and old image. Diagnose and retest before trying again. Never run old and new engines against the same state.
6. Once each host passes its acceptance checks, delete only this migration's temporary state copies, fixture data, unused old migration containers/volumes, and rollback image tags. Retain live state, real media, and normal managed backups. Fold the final operational behavior into the Flood runbook and remove this forward plan.

Update Gatus incident instructions to name the engine container, and deliberately attribute tailed job/engine logs to that engine while retaining the Flood service grouping. Verify the resulting central labels.

## Progress

- ✅ Confirmed the upload errors were not retained in current server logs and the combined upstream image is deprecated.
- ✅ Deployed the Flood collector and verified complete structured exceptions, severity and timestamps in ClickStack.
- ✅ Bilby now runs separate Flood 4.16.2 and rTorrent 0.16.24 containers; all 135 original torrents and eight settings matched before/after.
- ✅ Synthetic three-torrent uploads, hardlink publication, incomplete progress across container restart, and structured errors in ClickStack passed. The 218 backend tests and repository checks passed locally.
- ✅ Two independent reviewers completed the Bilby review; reproduced and corrected crash-lock recovery, narrowed exception serialization, matched source/runtime versions, and simplified init. Fork CI was green at 4faf5ac; follow-up changes are being tested.
- ✅ Follow-up review approved the resolved configuration. Private fork c7e369e passed all 219 tests and CI.
- ✅ Pinelake native builds, copied-state comparison of 38 torrents and all settings, real APFS hardlinks, and missing-sentinel rejection passed.
- Pinelake live deployment, final convergence and cleanup remain pending.
