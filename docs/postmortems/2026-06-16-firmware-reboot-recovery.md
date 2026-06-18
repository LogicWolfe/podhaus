# 2026-06-16 — QNAP firmware auto-update rebooted kangaroo; three containers stayed exited

**Status:** Resolved
**Severity:** Medium
**Trigger:** QTS firmware auto-update → kangaroo reboot

## Summary

QTS auto-applied a firmware update on kangaroo and rebooted the NAS. This
is a recurring, unscheduled event — firmware auto-update is on, so the
fleet must recover from it cleanly on its own. It didn't.

The `autorun.sh` boot hook did its job: Container Station's user Docker
engine came back, and the kangaroo containers on host-network or their
own compose network (`komodo-periphery`, `autoheal`, `syncthing`)
restarted via their `restart: unless-stopped` policy. But the two
kangaroo containers on the shared `dockernet` bridge — `backrest` and
`alloy` — lost the network-attach race at boot, exited, and nothing
brought them back. The restart policy gave up; autoheal only watches
*running* containers; Komodo's `BatchDeployStackIfChanged` saw no content
change. They sat in `exited` with a stored endpoint referencing a
dockernet ID the engine couldn't resolve during early boot.

On bilby, the same reboot took kangaroo's NFS server offline for the
duration (kangaroo serves Pouch + Jump). `flood`'s NFS-bind sentinel
healthcheck went red after ~3 minutes, and autoheal began restarting it
every ~30 s. One of those restarts, executed while the NFS bind was
mid-hang, wedged the container with a runc namespace error
(`failed to open /proc/.../ns/ipc`) and left it `exited`. Once exited it
dropped off autoheal's radar entirely (autoheal restarts *running*
unhealthy containers; an exited container has no health status), and the
Docker restart policy never engaged — `RestartCount` stayed `0`, because
the exit was the tail of an explicit `docker restart`, which Docker
deliberately does not auto-restart.

Net: three containers down across two hosts → six red Gatus panels. The
NAS itself stayed up the whole time (NFS served, both NICs reachable);
only the container-plane recovery gapped. The outage ran ~29 h before the
dashboard was surveyed.

## Timeline

Times AWST. The trigger fell in the early hours of 2026-06-17 AWST
(= 2026-06-16 20:1x UTC); this postmortem is filed under the UTC event
date to match the container `FinishedAt` stamps and in-repo references.

| Time (AWST) | Event |
|---|---|
| 2026-06-17 04:12 | kangaroo begins firmware-update reboot. `backrest` + `alloy` exit at shutdown (`FinishedAt=2026-06-16T20:12 UTC`). |
| 2026-06-17 04:15 | kangaroo boots (`uptime` boot stamp `Wed Jun 17 04:15 WST`). `autorun.sh` starts the CS Docker engine; `komodo-periphery`, `autoheal`, `syncthing` restart. `backrest` + `alloy` fail to re-attach `dockernet` and stay `exited` (`failed to create endpoint ... network 94d2b77a... does not exist`). |
| 2026-06-17 04:18–04:23 | On bilby, Pouch/Jump NFS is down during kangaroo's reboot. `flood`'s sentinel healthcheck goes red; autoheal restarts it 6× in 6 min. The final restart wedges it with a runc namespace error → `flood` `exited` (`RestartCount=0`; the policy never engages). |
| 2026-06-17 ~04:25 | Pouch/Jump NFS back as kangaroo finishes booting. The four bilby NFS-bind consumers other than flood ride it out; flood stays wedged. |
| 2026-06-18 ~09:00 | Gatus surveyed: six red panels (`Flood`, `Backrest (kangaroo)`, `Backrest Kangaroo Nightly`, `Kangaroo Log Ingest`, `RAR Extraction`, `Pinelake Stignore`). |
| 2026-06-18 ~09:20 | Root cause established: three containers, two hosts, one trigger; the firmware auto-update identified as the reboot cause (APC UPS + watchdog present, no clean-shutdown log). |
| 2026-06-18 ~09:30 | Recovery: `docker network disconnect -f dockernet {backrest,alloy}` to clear the stale endpoints, then `docker start` on kangaroo; `docker start flood` on bilby. All three healthy. |
| 2026-06-18 ~10:00 | Mitigations landed (commit `6b9bcb6`): patient healthcheck window, autorun reconcile, codified tripwire + sentinels. |

## Root cause

Three things compounded — one trigger, two independent recovery gaps that
turn out to be the same shape:

1. **`dockernet`-attach race at boot leaves linked containers parked in
   `exited`.** On the CS engine restart, the daemon tried to start
   `backrest` + `alloy` before `dockernet` was fully restored. The start
   failed; the restart policy exhausted its attempts and parked them in
   `exited`. The network exists now (same ID, `94d2b77a...`), so this was
   a timing race, not a missing network — but nothing retries an
   `exited` container whose config hasn't changed.

2. **The `exited`-container recovery seam.** Three independent
   mechanisms can bring a container back, and an `exited`-from-an-
   explicit-restart container falls between all of them:
   - `restart: unless-stopped` reacts to a process *crashing*, but
     deliberately steps aside after an explicit `docker stop`/`restart`
     (that's the contract that distinguishes it from `always`). autoheal
     recovers via explicit `docker restart`, so its own mechanism is
     exactly what suppresses the policy when its restart fails.
   - autoheal only restarts *running* containers reporting `unhealthy`.
     An `exited` container has no health status, so it drops off
     autoheal's selection set silently — autoheal didn't fail, it
     stopped *seeing* flood the instant it exited.
   - Komodo `BatchDeployStackIfChanged` only recreates on a content
     change; an unchanged exited stack is a no-op.
   `backrest`/`alloy` reached this seam via the boot race; `flood`
   reached it via an autoheal restart-storm. Same dead end.

3. **autoheal restart-storms an NFS-bind container during an NFS-server
   outage — which can wedge it.** When kangaroo (the NFS server) reboots,
   Pouch/Jump are gone for minutes. `flood`'s sentinel healthcheck
   (`retries: 3` → unhealthy in ~3 min) tripped, and autoheal restarted
   it every 30 s. Restarting can't fix a down NFS server, and tearing
   down/recreating the container's namespaces while I/O to the hung bind
   is in flight is what produced the runc namespace error that wedged it.
   The restart-storm was the hazard, not the cure.

The 2026-05-23 and 2026-05-30 postmortems hardened the *host-side* NFS
recovery (automount, sentinels, `chattr +i`, the wait-for-NFS gate).
Those defences worked here — zero data loss, no stub-bind writes. This
incident is the *container-plane* recovery gap they didn't cover.

## Impact

- **No data loss.** The NAS stayed up serving NFS the entire time; the
  Pouch/Jump shares and the restic repos were untouched. The
  `chattr +i` tripwire + sentinels were never exercised (this was a
  stale-mount, not a stub-bind).
- **Service degradation (~29 h):** flood's torrent UI + the RAR
  extraction pipeline down; kangaroo's nightly backrest snapshot for the
  night of 2026-06-16→17 did not run; kangaroo container-log shipping
  (`alloy`) stopped, so the `Kangaroo Log Ingest` staleness check went
  red and that window of kangaroo logs is absent from ClickStack.
- **Monitoring:** all six affected panels reported correctly — the gap
  was that nothing *recovered* the containers, not that nothing noticed.

## Resolution

All landed in commit `6b9bcb6` unless noted.

### In-repo

- [x] **2026-06-18**: `kangaroo/host-autorun/autorun.sh` — after the CS
  engine is up, reconcile any `exited` container whose restart policy is
  `always`/`unless-stopped`: `docker network disconnect -f` to clear the
  stale endpoint, then `docker start` (one-shot inits with `restart:no`
  are skipped). Closes gaps (1) and (2) for kangaroo at boot. Deployed
  via the existing `install.sh` (copies the tracked script to the boot
  DOM); proven only on the next firmware reboot.
- [x] **2026-06-18**: Patient healthcheck window — `retries: 3 → 15` (at
  `interval: 60s` ≈ 15-min patience) on the four NFS-bind consumers
  (`flood`, `plex`, `paperless`, bilby `backrest`). A kangaroo NFS outage
  now rides out without autoheal restart-storming; one successful probe
  after NFS returns resets to healthy in ~60 s. Closes gap (3).
- [x] **2026-06-18**: `bilby/host-systemd/install.sh` — codified the
  `chattr +i` mountpoint tripwire (applied idempotently on a live host
  via a non-recursive `mount --bind /` to reach the bare btrfs dir under
  the NFS overlay) and the six share sentinels. These were hand-applied
  in the 2026-05-23 remediation and never reproducible — a Pouch RAID
  rebuild wipes the sentinels, a fresh host has no tripwire.

### Recovery (operational)

- [x] **2026-06-18**: kangaroo — `docker network disconnect -f dockernet
  backrest alloy && docker start backrest alloy`. A plain `docker start`
  failed with "network ... does not exist" despite `dockernet` being
  present; the stopped containers held a stale endpoint that had to be
  cleared first.
- [x] **2026-06-18**: bilby — `docker start flood`.

### Documentation (in-repo)

- [x] **2026-06-18**: This postmortem.
- [x] **2026-06-18**: `docs/postmortems/index.html` — table entry.
- [x] **2026-06-18**: `AGENTS.md` — Postmortems list entry.
- [x] **2026-06-18**: `docs/stack-conventions.html` — patient-window
  guidance for NFS-bind containers + the autoheal/restart-policy seam.

## What we learned

- **An `exited` container with unchanged config is recovered by
  nothing.** The restart policy (suppressed after an explicit restart),
  autoheal (watches *running* unhealthy), and Komodo IfChanged (recreates
  on change) each cover a different container state, and an exited-from-
  an-explicit-restart container falls between all three. A reconcile that
  acts on "should be running, isn't, regardless of why" is the only thing
  that covers it — on kangaroo that's the boot autorun.

- **autoheal and the restart policy interfere.** autoheal recovers via
  explicit `docker restart`, which is precisely the operation that
  disables `restart: unless-stopped`. So when an autoheal restart fails
  halfway, the policy you'd hope catches the fallout is, by design,
  switched off. Don't reason about them as additive safety nets.

- **More restarting is the hazard, not the cure, for an NFS-bind
  container whose server is down.** autoheal already restarts
  indefinitely (no retry cap — it restarted flood 6× before the wedge);
  the `retries` knob is a *detection* threshold, not a restart limit.
  Restarting can't fix a down NFS server, and doing it repeatedly while
  the bind hangs risks wedging the namespace. The right lever is a
  patient detection window so the storm never starts for a transient
  outage.

- **A stale network endpoint survives a reboot and breaks `docker
  start`.** "network ... does not exist" can mean "the stopped
  container's stored endpoint is stale," not "the network is gone."
  `docker network disconnect -f` then `start` clears it; a recreate
  (`compose up -d`) would too. A naive `docker start` reconcile is
  insufficient.

- **Recurring auto-reboots demand automated container-plane recovery,
  not just host-plane.** Firmware auto-update makes a kangaroo reboot a
  when-not-if event. The host-side automount/sentinel/tripwire work from
  the prior two postmortems wasn't enough on its own — the containers
  also have to come back, and that's a separate set of mechanisms.

## Out of scope

- **A bilby periodic exited-container reconcile.** The kangaroo reconcile
  is boot-triggered, which fits because kangaroo reboots. bilby's flood
  wedge happened with bilby *up*, so a boot hook wouldn't catch it — only
  a periodic reconcile would. Deliberately **declined**: the patient
  window makes the wedge unlikely, and the residual failure mode (a wedge
  to `exited` needing a manual `docker start`) was accepted rather than
  add a periodic supervisor. If flood (or another NFS-bind consumer)
  wedges again in practice, reopen this.

- **Controlling firmware auto-update cadence.** QTS can be set to
  download-only / scheduled so the reboot is planned rather than a
  surprise. Recovery is now automatic either way, so this is optional;
  not changed.

- **Cold-boot validation of the autorun reconcile.** Proven only on the
  next real firmware reboot — we don't reboot kangaroo to test. The
  reconcile logs to `/var/log/komodo-periphery-boot.log` on kangaroo, so
  the next reboot leaves a trace of what it recovered.

## Related

- `kangaroo/host-autorun/autorun.sh` — the boot hook + reconcile loop.
- `bilby/host-systemd/install.sh` — host tripwire + sentinels, now
  codified.
- `docs/stack-conventions.html` — NFS-bind healthcheck + patient-window
  guidance.
- `docs/postmortems/2026-05-23-pouch-jump-mount-failure.md` — introduced
  the sentinel healthchecks + `chattr +i` tripwire (host-plane).
- `docs/postmortems/2026-05-30-power-outage-nfs-recovery.md` — the
  boot-time NFS race + Gatus false-green; closed the host-plane boot
  ordering. This incident is the container-plane analogue.
