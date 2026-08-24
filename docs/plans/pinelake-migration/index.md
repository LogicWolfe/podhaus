# Pinelake cutover

## Goal

Bring Pinelake into Podhaus as an unattended media appliance without changing
its Plex identity or losing Plex, Flood, Syncthing, or TerraMaster state. The
finished host uses the fleet's current-image Compose, Komodo, backup, ingress,
and monitoring patterns. Native services, Colima, cloudflared, and recovery
archives remain available until rollback is separately released.

## Fixed contract

- OrbStack is the sole deployed container runtime, selected globally. No
  deployed command names a Docker context or pins an old release.
- Plex, Syncthing, and Flood become Komodo-managed containers. Plex uses
  `plexinc/pms-docker:latest`; software transcoding is the expected macOS path.
- Any Plex-visible media move, Plex stop/restart/redeploy, runtime restart, or
  reboot requires two successful zero-session checks. An unavailable endpoint,
  malformed response, or non-zero count aborts. Automatic recovery is allowed
  only when the process, listener, and port are all proven absent.
- Plex automatic trash emptying remains disabled. Native and container Plex
  never present the same identity to plex.tv simultaneously.
- The TerraMaster must be writable APFS UUID
  `EAED18A9-74C7-4163-ACB4-406B2226FDC6`; its sentinel must match and the exact
  required paths must be visible through OrbStack before any writer starts.
- Pouch is authoritative and fully recovered. Pinelake is never a recovery
  source for Pouch.
- Syncthing is one-way: Kangaroo send-only, Pinelake receive-only. Its four
  folders are Movies, TV, Kids, and Sports. The normal source `.stignore` files
  live on Kangaroo only. The empty Pinelake receive roots remain Plex library
  locations alongside the Flood targets so both future ingestion paths work.
- Corrupt or incomplete RAR sets may be deleted. A valid set is deleted only
  after its extracted media is verified.
- JetKVM remains unchanged and is a failure-recovery path, not a planned
  operating dependency.

## Plex identity gate

| Surface | Required value |
|---|---|
| `MachineIdentifier` | `c9d75740-0fd3-4bba-9874-be61f5dc8d38` |
| `ProcessedMachineIdentifier` | `92311858cdd55fb33583fda2e6fc037e3655da85` |
| `AnonymousMachineIdentifier` | `166ee17f-2122-4dcf-9d5e-38961c51ff25` |
| `CertificateUUID` | `5801df40ceea4deaaefd8bd027fc22ff` |

Never use `PLEX_CLAIM`, first-use setup, sign-out, or an empty preferences file.
The raw and processed identifiers are different by design and must be checked
at every migration boundary.

## Completed foundation

- ✅ The live host, Plex library, watched/resume canaries, launchd state,
  cloudflared, Flood, both Colima profiles, both Syncthing endpoints, OrbStack,
  mount identity, and power policy were inventoried into redacted manifests.
- ✅ Native Plex was stopped only after two zero-session checks, its complete
  state was captured as an APFS clone, its database passed Plex SQLite's
  integrity check, and native Plex was restarted with its identity intact.
- ✅ Kangaroo's 12 GB Syncthing configuration and index were copied to Jump and
  restored to service. Pinelake's retired identity and index are archived.
- ✅ Flood and both Colima profiles were stopped cleanly. Their launch agents,
  configuration, container/image manifests, and data remain recoverable.
- ✅ Current OrbStack is globally selected; the Colima Docker context is gone.
  Ansible owns power policy, OrbStack settings/startup, operational gates,
  mount sentinel, Pomerium SSH trust, and outbound Periphery. The second real
  playbook application reports `changed=0`, and Core reports Periphery healthy.
- ✅ The removable-volume failure was identified as an ungranted macOS
  `kTCCServiceSystemPolicyRemovableVolumes` request for OrbStack's signed bundle.
  The grant is now approved and persisted (`authValue=2`). A cold OrbStack
  start passed sentinel read, disposable write/delete, and current Plex,
  Syncthing, and Flood image probes. Service definitions expose only their
  required media roots rather than the whole TerraMaster tree and refuse to
  create missing host paths.
- ✅ Four ordinary source `.stignore` files now permanently exclude operating
  system metadata, release metadata, archives, and partial downloads above an
  empty whitelist slice and final `**`. Artwork and subtitles remain eligible.
- ✅ Kangaroo's paused whole-Pouch folder and retired Pine Lake device were
  removed. Four new send-only folders advertise zero files:

  | Folder ID | Kangaroo root | Pinelake root |
  |---|---|---|
  | `pinelake-movies` | `/share/CACHEDEV1_DATA/Pouch/Movies` | `/Volumes/TerraMaster/Movies` |
  | `pinelake-tv` | `/share/CACHEDEV1_DATA/Pouch/TV` | `/Volumes/TerraMaster/TV` |
  | `pinelake-kids` | `/share/CACHEDEV1_DATA/Pouch/Kids` | `/Volumes/TerraMaster/Kids` |
  | `pinelake-sports` | `/share/CACHEDEV1_DATA/Pouch/Sports` | `/Volumes/TerraMaster/Sports` |

- ✅ Pinelake's fresh Syncthing identity is
  `A3M4ONB-5IMEMPV-S5DMZBP-XBA5Q5D-U7V67DR-JZDJVE4-QVIU4T2-SJYITAJ`; it is
  paired with those four Kangaroo folders but has inherited no old index.
- ✅ The 2,771-file relocation manifest was built with no-overwrite,
  crash-resumable same-filesystem operations. All 20 existing targets are
  hash-equal; any mismatch would have aborted planning.
- ✅ A disposable Plex state copy was converted from the macOS plist and
  started under the current Plex container image with networking disabled.
  All four identity values, state counts, and library databases matched; the
  disposable copy was then removed without feeding state back to native Plex.
- ✅ The complete critical-state archive, exact native Plex application,
  post-capture manifests, and fresh Syncthing/Flood staging were copied to
  Jump with recorded SHA-256 digests. A full scratch restore passed both Plex
  database integrity checks and matched the baseline database digest and all
  four identity values. Encrypted restic snapshot `5075e8fc` was
  fully restored and checksum-verified, then mirrored to OneDrive with 3,769
  matching files and zero differences.
- ✅ All six legacy RAR sets were already extracted at their audited names and
  sizes. Cleanup removed 138 RAR pieces and 12 scene metadata files; a fresh
  full-volume search found zero remaining RAR files.
- ✅ The relocation manifest was applied after two zero-session checks and the
  exact mount guard. All 2,751 moves retain their original device, inode, and
  size; all 20 proven-equal duplicates have one retained target; no file
  remains in an old receive root.
- ✅ Native Plex scanned the consolidated targets. Every one of the 1,640
  relocated Plex media parts resolves at its new path and remains attached to
  the same metadata item. Watched (3,587), in-progress (48), and rated (8)
  canaries are unchanged. The empty Syncthing receive roots remain configured
  as Plex library locations for future selections.
- ✅ Fixture tests cover session refusal, identity conversion, dead-process
  recovery, exact mount identity, collision-safe relocation, pre-deploy gates,
  and the four-file `.stignore` contract. Repository lints and Pinelake Compose
  renders pass.
- ✅ Bilby and Fractal now use their sole canonical per-host development
  service accounts with read-only Dev and read/write Homelab access. The
  superseded per-host accounts and the retired shared Homelab service account
  were deleted. Terraform published Pinelake's rathole tokens and logging
  client certificate into the existing Homelab items without changing DNS,
  ingress, or a running service.

## Remaining dependency chain

### 1. Finish native-state normalization

- Backfill all 28 legacy torrent sessions through the shared publish and Plex
  label logic. Leave incomplete torrents untouched.
- Recheck artwork, sharing, labels, identity, and the target-path accounting
  after the torrent backfill. Keep the empty old roots as the future Syncthing
  ingestion locations in each Plex library.

### 2. Publish fleet configuration

- Create the dedicated Pinelake Plex token item and independent Pinelake
  OneDrive OAuth snapshot in the Homelab vault.
- Commit and push the reviewed Podhaus change as an explicit deployment
  boundary. ResourceSync must register Pinelake and its linked repo before any
  application stack is deployed.
- Deploy and verify Numbat relay listeners, Pomerium routes, Pinelake Caddy,
  logging, monitoring, backup, Autoheal, and Ofelia. Plex remains outside
  generic Autoheal.

### 3. Cut over Syncthing and Flood

- Deploy Pinelake Syncthing, configure the four receive-only folders against
  the existing fresh identity, and confirm all four global/local/needed counts
  begin at zero. No `.stignore` is installed on Pinelake.
- Prove one controlled selection in each folder family. Only the corresponding
  normal source `.stignore` may change; permanent junk remains absent while
  media, artwork, and subtitles arrive. Pouch must remain unchanged.
- Import the 28 stopped Flood sessions into the shared Bilby implementation
  without a forced recheck. Verify hashes, names, completion, tags, paths, and
  resume state.
- Exercise one new controlled download through redirect, extraction,
  hardlink publication, Plex labeling, backlog monitoring, and native
  remove-and-delete behavior. Require zero extraction and publish backlog.

### 4. Cut over Plex last
- Capture the final baseline, pass the session gate twice, stop native Plex,
  and prove its process, listener, and port are absent.
- Capture a final immutable native archive and fresh container-state clone.
  Convert and verify `Preferences.xml`, then create the cutover-ready marker
  that allows the Komodo pre-deploy gate to start the container.
- Start isolated, verify identity and all user-visible state, then enable normal
  networking and verify LAN, remote access, discovery, playback, and software
  transcoding. Keep the native application, plist, and state untouched.

### 5. Prove unattended operation

- Move `sync.pinelake.haus` and `torrent.pinelake.haus` to the proven Numbat
  route. Stop but retain cloudflared; keep `home.pinelake.haus` for rollback
  until the migration is released.
- Take and restore representative Plex, Syncthing, Flood, Periphery, and host
  backups. Verify monitoring and backup freshness.
- After two zero-session checks, cold reboot through the normal management
  path. Automatic login, TerraMaster, OrbStack, Periphery, every workload,
  ingress, telemetry, and backup must return without JetKVM or human action.
- Exercise an OrbStack restart and a current-image Plex redeploy through the
  same session gate. Remove temporary Tailscale access only after Pomerium SSH
  passes off-LAN and after reboot.

## Rollback boundaries

| Boundary | Rollback |
|---|---|
| Media relocation | Reverse the manifest. Recreate deduplicated sources as hardlinks to their proven equal targets. |
| Fresh Syncthing | Stop the new container and remove the four new folder relationships. The retired state archive is configuration recovery only, never a Pouch data source. |
| Flood | Stop managed Flood and OrbStack, reconstruct the preserved Colima context, and start the untouched legacy container and session tree. |
| Plex | Stop the container without cleanup, start the untouched native application/state/plist, and verify every identity surface before clients reconnect. Never feed a container-upgraded database to older native Plex. |
| Ingress | Restart preserved cloudflared and restore the previous DNS records. |

RAR cleanup has no archive rollback by explicit decision: verified extracted
media is retained; corrupt/incomplete sets and disposable pieces are deleted.

## Completion gate

- No pre-migration media remains in old Syncthing-fed roots; every relocated
  item is available from a Flood/Plex target with Plex state unchanged. The
  roots remain active library locations for future Syncthing selections.
- The four fresh Syncthing folders remain one-way and inherit no old index.
- Existing and new Flood items use the shared extraction, publication,
  labeling, monitoring, and cleanup behavior; no RAR or publish backlog remains.
- Plex retains every required identity and user-visible state surface.
- OrbStack is the global unqualified Docker engine; its removable-volume grant
  survives cold start and no deployed command names a context.
- A restore, runtime restart, current-image Plex deployment, and cold reboot
  pass without manual intervention.
- Native services, Colima, cloudflared, temporary access state, and recovery
  archives remain available until separately approved for deletion.
