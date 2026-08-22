# 2026-08-22 — Delayed NFS recovery left containers and jobs stopped

**Status:** Resolved
**Severity:** Medium
**Trigger:** hard power reset of Bilby and QNAP

## Summary

A power reset rebooted Bilby before the QNAP NFS server was reachable. Bilby's
finite `wait-for-qnap-nfs.service` spent 200 seconds probing TCP/2049, timed out,
and allowed Docker startup to continue. Jump and Pouch mounted about three
minutes later, but Flood and StreamFab Publish had already failed at the OCI bind
step with `no such device`. Both remained exited even after their required Pouch
mount became valid. Docker's restart policy did not retry them, and Autoheal
could not select an exited container whose last health state was `starting`.

Manual starts recovered both containers. Restarting Ofelia was also required
because the stable `v0.3.22` scheduler reads Docker labels only at startup. Its
first recovered StreamFab run then exposed an independent permission defect:
the script was mode `0600` in both the working checkout and root-owned deploy
tree, so scheduled uid `1000` could not read it. The same latent defect existed
on Flood's Plex Label Sync script and four Compose/TOML files. Restoring the
Git-intended `0644` modes allowed all jobs and heartbeats to recover.

The six bad modes originated when Claude Code created the files during assisted
work on 25–27 June. They match the reproduced Linux `Write` bug in Anthropic's
issue tracker, which hard-coded `0600` rather than applying the process umask.
Git and later edits preserved an invisible local difference, and the deploy
mirror faithfully copied it; the mirror did not create it.

The hard reset also left `/boot/efi` dirty. Its fstab pass number is `0`, so no
boot-time filesystem check ran. Recovery repaired and verified the FAT32 volume
offline. No data was lost. At closeout, systemd reported `running`, all intended
containers were healthy, all five Komodo hosts reported `Ok`, Fractal's Forgejo
runner was polling, and Gatus had 44 of 45 endpoints green; the excluded Yiayia
board was the sole remaining failure.

Follow-up validation upgraded Ofelia to `0.4.0-beta.5` and proved its
Docker-event reload at the deployed boundary. Comparing labels with the live
schedule exposed a separate pre-existing defect: Backrest's documented
`forgejo-backup-recover` job lacked the required `ofelia.enabled=true` label and
had therefore never registered. The label was added, Backrest alone was
recreated, and beta5 registered and successfully ran the job without an Ofelia
restart.

The completed preventive change replaced the finite pre-Docker delay with a
recurring, mount-aware systemd recovery timer. It starts only opted-in
always-on containers parked in `created` or `exited` by a retained Jump/Pouch
OCI mount error, and only after the exact NFS export and sentinel are healthy.
The Ofelia deployment restart workaround was removed after the beta passed its
live boundary tests, and `/boot/efi` now has fstab pass number `2` so systemd
checks it before mounting.

## Timeline

Times are AWST on 2026-08-22.

| Time | Event |
|---|---|
| 08:11:17 | Bilby boots after the hard power reset. The kernel reports that `/dev/nvme0n1p4` was not properly unmounted and requests `fsck`. |
| 08:11:25 | `wait-for-qnap-nfs.service` starts probing `10.0.0.25:2049`; attempts initially fail with `Network is unreachable`, then `No route to host`. |
| 08:14:45 | The wait unit reaches `TimeoutStartSec=200`, is terminated, and enters failed state. Docker startup begins because the dependency is `Wants=`, not `Requires=`. |
| 08:14:50–08:17:42 | Docker restoration repeatedly triggers the Jump and Pouch automounts while QNAP remains unavailable. |
| 08:15:36 | StreamFab Publish fails its `/mnt/pouch` → `/data` OCI bind with `no such device`. |
| 08:16:21 | Flood fails the same OCI bind and becomes parked exited. |
| 08:17:41 | Jump mounts from `10.0.0.25:/Jump`. |
| 08:17:42 | Pouch mounts from `10.0.0.25:/Pouch`. Fractal's Forgejo runner successfully declares labels `podhaus-ci-x64` and `podhaus-browser-x64` after earlier connection failures and launches its poller. |
| 08:17:43 | Docker finishes startup. Flood and StreamFab remain exited despite valid storage. |
| 08:31:14 | Brinno downloader, which had become unhealthy during the outage, recovers automatically. |
| Before 09:06 | Audit confirms both NFS exports and sentinels valid, all five Komodo servers reachable, and Flood plus StreamFab as the only unintended stopped services. Ofelia has registered only five jobs; StreamFab Publish and Plex Label Sync heartbeats are stale. |
| 09:06:56 | `docker start flood` succeeds. |
| 09:06:57 | `docker start streamfab-publish` succeeds. Both containers become healthy. |
| 09:07:04 | Ofelia is restarted. At 09:07:06 it registers ten jobs, including Flood Publish, StreamFab Publish, Plex Label Sync, and Pine Lake Stignore. |
| 09:08:00 | StreamFab's first scheduled run fails: `python3: can't open file '/scripts/streamfab-publish.py': [Errno 13] Permission denied`. |
| 09:08:58 | StreamFab's script is restored from `0600` to `0644` in the working and deploy trees. A recurrence sweep finds the same drift on Flood's Plex Label Sync script and four stack definition files. |
| 09:09:00 | StreamFab Publish completes successfully and restores its Gatus heartbeat. |
| 09:10:00 | Plex Label Sync and Pine Lake Stignore complete successfully. Every scheduled heartbeat is green. |
| 09:14 | `/boot/efi` is unmounted. `fsck.fat -n` finds the dirty bit and a one-byte boot-sector/backup mismatch but no lost chains. `fsck.fat -a` repairs it; a second read-only pass is clean and the volume is remounted. |
| 09:14:32 | The obsolete failed NFS wait unit is reset. `systemctl is-system-running` returns `running`. |
| 09:16 | Final validation: Gatus 44/45 with only excluded Yiayia red; Bilby, Kangaroo, Numbat, Fractal, and Voltaire are `Ok`; Fractal's runner remains registered and polling. |
| 10:14 | Ofelia is upgraded to pinned `0.4.0-beta.5`. Event-driven add, replace, and remove tests pass without restarting it. |
| 10:17 | Schedule reconciliation finds the missing `ofelia.enabled=true` label on Backrest. Backrest alone is recreated with the label and Ofelia immediately registers `forgejo-backup-recover` from the Docker event. |
| 10:20 | `forgejo-backup-recover` runs successfully. All 11 enabled production jobs are represented once; real minute jobs and their Gatus heartbeats remain green. |
| 11:25 | The `nfs_binds` Ansible role removes the finite Docker startup gate, installs and starts the recurring recovery timer, and changes `/boot/efi`'s fstab pass number to `2`. |
| 11:29 | A disposable real-Docker bind failure confirms that fresh OCI start failures remain in `created`, that failed recovery is visible in the unit journal, and that the timer starts the same container after its bind source becomes valid. The probe container and files are removed. |
| 11:34 | The timer continues completing cleanly with no candidates. Unit tests cover both NFS exports, autofs-plus-NFS `findmnt` output, `created` and `exited` states, operator stops, invalid mounts, and visible start failure. |

## Root cause

Five defects compounded.

1. **The QNAP wait is a finite startup delay, not recovery.** It tests only
   TCP/2049, is bounded by `TimeoutStartSec=200`, and runs once before Docker.
   QNAP became available after that window. Making the delay longer would move
   the threshold without supporting storage that returns hours later or
   disappears while Bilby remains running.

2. **Exited OCI-start failures have no owner.** Flood and StreamFab use
   `restart: unless-stopped`, but Docker did not retry after their OCI bind
   failures. Autoheal selects Docker health `unhealthy`; both containers were
   exited with their last health state still `starting`. Komodo correctly did
   nothing because configuration was unchanged and recovery is not a deployment
   concern. Once Pouch returned, nothing reconciled desired running state.

3. **Stable Ofelia does not discover late containers.** Bilby runs
   `mcuadros/ofelia:latest`, currently image version `v0.3.22`. It built its
   schedule before Flood and StreamFab were available and retained only five
   jobs. A restart after container recovery was required to discover all ten.
   Upstream Docker-event hot reload has landed in `v0.4.0-beta.5`, but not in
   the stable `latest` tag.

4. **Claude Code created new files with hard-coded private modes.** All six
   affected files were born during Claude-assisted work on 2026-06-25–27; five
   share the recorded Claude session `session_01M9x26xz2ds9fpuYn2nWxci`, and
   the sixth was the sole new file in another Claude-assisted commit. The
   pattern matches Anthropic's reproduced Linux bug in which the `Write` tool
   created files as `0600` regardless of umask. Git records ordinary files as
   `100644` or `100755`, so it hid the local `0600` versus `0644` distinction.
   Later edits preserved the existing modes. `podhaus-load-local-tree` then
   correctly copied those modes into the root-owned deploy tree, where container
   uid `1000` could not read the scripts.

   The original tool-call transcript is no longer available locally, so the
   attribution is high confidence rather than syscall-proven. The shared
   Claude-assisted creation provenance, surviving birth timestamps, exact
   `0600` mode, lack of any matching shell command, and the reproduced upstream
   behaviour converge on the same cause.

5. **EFI checking was disabled by fstab metadata.** `/boot/efi` is configured
   with pass number `0`, so systemd generated no `systemd-fsck@` dependency for
   the mount. The kernel detected the dirty FAT volume but nothing repaired it
   during boot.

An independent latent scheduling defect was found during follow-up validation:
Backrest had the `forgejo-backup-recover` schedule and command labels but not
the required `ofelia.enabled=true` opt-in. This was a one-line configuration
omission, not a beta regression or a result of the outage.

## Impact

- **No data loss.** The immutable bare-mount tripwires and share sentinels kept
  consumers from writing to Bilby's local disk while NFS was absent. The EFI
  check found no lost chains or directory damage.
- Flood was unavailable from Docker restoration until 09:06:56.
- StreamFab publishing remained stopped until 09:09. Completed source files
  stayed in the inbox and were processed after recovery.
- Plex Label Sync had a stale heartbeat predating the reboot. Its first recovered
  scheduled run completed at 09:10, applying any pending additive labels.
- Fractal's Forgejo runner could not declare while Forgejo was unavailable, then
  recovered automatically at 08:17:42 without manual intervention.
- The Forgejo backup recovery backstop was not scheduled before 10:17 because
  Backrest lacked Ofelia's required enable label. No interrupted backup lock was
  present during this interval, so Forgejo needed no recovery action.
- Other storage consumers recovered without intervention. Brinno's delayed
  recovery demonstrated that the patient healthcheck and Autoheal path still
  works for a running container that becomes unhealthy; it did not cover the
  exited OCI-start state.
- Bilby remained `degraded` after service recovery solely because the one-shot
  NFS wait unit retained its failed state. Resetting it restored a clean systemd
  state.

## Resolution

### Operational recovery

- [x] **2026-08-22**: Verified Jump and Pouch resolve to the expected QNAP NFSv4
  exports and both `.podhaus-share-mounted` sentinels are readable.
- [x] **2026-08-22**: Started Flood and StreamFab Publish individually; both
  cleared their Docker errors and became healthy.
- [x] **2026-08-22**: Restarted Ofelia and verified all ten jobs registered.
- [x] **2026-08-22**: Verified successful executions of Flood Publish,
  StreamFab Publish, Plex Label Sync, Pine Lake Stignore, Sky cache invalidation,
  and search indexing.
- [x] **2026-08-22**: Restored `0644` on the six affected working/deploy-tree
  files: both scheduled Python scripts, StreamFab's Compose/TOML files, and
  Umami's Compose/TOML files.
- [x] **2026-08-22**: Accepted that manual mode correction as the complete
  resolution for the permission defect. No Claude hook, deploy-mirror preflight,
  permission linter, or other ongoing regression work will be added.
- [x] **2026-08-22**: Repaired `/dev/nvme0n1p4` offline, verified a clean second
  `fsck.fat -n` pass, and remounted `/boot/efi` with its original options.
- [x] **2026-08-22**: Cleared `wait-for-qnap-nfs.service`'s retained failure and
  verified systemd, firewalld, NTP, disk capacity, mounts, containers, Gatus,
  Komodo hosts, and Fractal's runner.
- [x] **2026-08-22**: Upgraded Ofelia to pinned `0.4.0-beta.5` and validated
  event-driven job add, replacement, and removal against the deployed Docker
  daemon without restarting Ofelia.
- [x] **2026-08-22**: Added the missing `ofelia.enabled=true` label to Backrest,
  observed beta5 register `forgejo-backup-recover` from the recreate event, and
  verified its first real run succeeded.

### Preventive implementation

- [x] **2026-08-22**: Replaced the finite pre-Docker wait with a recurring,
  mount-aware stopped-container reconciler. Autoheal remains the owner of
  running unhealthy containers. Recovery reuses the existing `autoheal=true`
  opt-in, always-on restart policy, Docker bind sources, and matching retained
  OCI mount error; it adds no recovery labels or stack linter.
- [x] **2026-08-22**: Removed the Komodo deployment-boundary Ofelia restart.
  Ofelia-specific behavior is absent from storage recovery; the deployed beta's
  event reload owns schedule discovery.
- [x] **2026-08-22**: Brought Bilby's existing EFI fstab entry under Ansible
  ownership with pass number `2`, preserving its UUID, type, mount point, and
  options so systemd uses its normal pre-mount FAT check.

### Documentation

- [x] **2026-08-22**: Added this postmortem and its `AGENTS.md` index entry.
- [x] **2026-08-22**: Updated the durable storage, provisioning,
  stack-convention, scheduling, Komodo, architecture, and service-runbook docs
  to the accepted runtime contract, then retired the completed plan.

## What we learned

- A startup delay is not recovery. Remote storage readiness has no useful upper
  bound, and the same failure can happen without a host reboot. Reconciliation
  must recur for the life of the host and validate the exact mounted share.
- Docker restart policy, Autoheal, and Komodo each own a different state. An
  exited container with an OCI infrastructure error and unchanged configuration
  belongs to none of them unless that state is explicitly reconciled.
- A fresh OCI bind failure can remain in Docker's `created` state rather than
  `exited`; recovery eligibility must accept both while retaining every other
  narrow predicate.
- On a systemd automount, `findmnt --target` reports the autofs wrapper and the
  mounted NFS child. Readiness must select the exact expected NFS source rather
  than assume a single row.
- Recovering a scheduled-job container is incomplete until the scheduler has
  discovered its labels. Validate the heartbeat or execution, not just container
  health.
- Git status cannot detect owner/group/other read-mode drift on an ordinary
  tracked file. Prevent a known creator from introducing the drift; do not make
  every downstream consumer compensate for it.
- A successful mount after a hard reset does not prove filesystem integrity.
  fstab pass numbers are part of the recovery contract, not incidental metadata.
- Gatus result arrays are chronological. Recovery validation must select the
  result with the newest timestamp rather than assuming the first element is
  current.

## Out of scope

- **Yiayia Board Device:** remained HTTP 503 and was explicitly excluded from
  this recovery.
- **`sudo` PAM warnings:** privileged commands logged a failure to inspect
  `/run/user/0/bus` but completed successfully. This was log noise, not a
  recovery failure.
- **SSH remote-forward warning:** a direct Fractal check reported that remote
  port 18339 was already in use. The SSH command and runner checks succeeded; an
  existing tunnel already owned the port.

## Related

- [2026-05-30 power-outage NFS recovery](2026-05-30-power-outage-nfs-recovery.md)
- [2026-06-16 firmware reboot recovery](2026-06-16-firmware-reboot-recovery.md)
- [Storage](../storage.html)
- [Monitoring](../monitoring.html)
- [Scheduling](../scheduling.html)
- [Ofelia v0.4.0-beta.5 release](https://github.com/mcuadros/ofelia/releases/tag/v0.4.0-beta.5)
- [Merged Ofelia Docker-event reload](https://github.com/mcuadros/ofelia/pull/445)
- [Superseded Ofelia Docker-event hot-reload PR](https://github.com/mcuadros/ofelia/pull/368)
- [Claude Code Write tool hard-coded `0600` issue](https://github.com/anthropics/claude-code/issues/12172)
