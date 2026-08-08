# 2026-08-08 — bilby global OOM tore down the user session, which never came back

**Status:** resolved
**Severity:** medium
**Trigger:** an ESPHome build on a host whose swap was already 100% full

## Summary

bilby ran out of memory at 13:32:44 AWST. Swap had been fully consumed for
some time; a parallel ESPHome firmware build spawned nine concurrent
`cc1plus` processes holding ~1.2 GB of freshly-touched, unswappable pages,
and the kernel entered a global OOM with no reclaim path left.

The kernel's victim selection spent five kill cycles on processes averaging
under 3 MB — including `systemd`, the per-user service manager — before
reaching `clickhouse-serv`, whose 884 MB actually ended the event. Killing
the user manager caused systemd to tear down all of `user@1000.service`,
taking the operator's tmux server, five fish shells, four `claude` sessions
and a `docker` client with it. The visible symptom was "my tmux session died
with no obvious cause"; nothing in the logs says the word tmux.

Two containers were casualties and both recovered automatically within a
second. The lasting damage was elsewhere and silent: `user@1000.service`
stayed in `failed` state for 2h32m — logind never restarts it once sessions
already exist — so `machine-ssh-agent` remained dead and SSH from bilby to
every other host was impossible. Separately, fractal's Alloy stopped shipping
telemetry at 13:32:47 and never resumed, while continuing to report
`healthy`, costing 2h41m of logs.

## Timeline

Times AWST (UTC+8). Clock was reliable throughout; no reboot occurred
(bilby had 69 days uptime before and after).

| Time | Event |
|---|---|
| — | Swap sits at 8.0 GiB / 8.0 GiB used, ~1 MiB free. 38 containers run with no memory limit; ClickStack alone accounts for ~2.25 GB |
| ~13:30 | ESPHome build starts in the operator's tmux session; ninja fans out to 9 concurrent `cc1plus` (~1.2 GB RSS, no swap backing) |
| 13:32:19 | fractal Alloy begins logging `Exporting failed … TLS handshake timeout` against `logs-ingest.pod.haus` |
| 13:32:44 | bilby's `numbat-rathole-client` logs heartbeat timeout and noise-handshake failures to numbat |
| 13:32:44–45 | Kernel global OOM. Five `oom-killer` invocations kill `dbus-broker-lau` (2 MB), `ssh-agent` (1.6 MB), `dbus-broker` (1.5 MB), `systemd` user manager (6 MB), `(sd-pam)` (2.3 MB) — ~13 MB freed in total |
| 13:32:45 | `clickhouse-serv` killed, exit 137, 884 MB reclaimed. This ends the OOM |
| 13:32:45 | systemd tears down `user@1000.service`: `Killing process … (fish)` ×5, `(claude)` ×4, `(docker)`, `(bash)`. tmux server dies as a child of the cgroup. Unit enters `failed` |
| 13:32:46 | Docker restart policy recreates `clickstack-clickhouse` (exit 137) and `pocket-id` (exit 1) |
| 13:32:47 | fractal `komodo-periphery` logs `Logged in to Komodo Core … as Server fractal` — its last log line. Alloy stops exporting and stops logging entirely |
| 14:01:01 | Operator starts a fresh tmux session by hand |
| ~14:04 | Investigation begins from "tmux died, no obvious cause" |
| ~15:50 | `user@1000.service` found still `failed`, 2h18m on; no `systemd --user` process for uid 1000 |
| 16:02 | Manager restored via `reset-failed` + `start`; `machine-ssh-agent` returns with its PIV key, SSH usable again |
| 16:09 | fractal reached over SSH: host up 5 days, load 0.00, all six containers `Up 5 days` and healthy. Live probe traffic confirms Alloy is accepting logs but not shipping them |
| 16:14:10 | fractal Alloy restarted; ingestion resumes, verified end-to-end (105 rows within 12 minutes) |
| 16:30 | `user@.service` restart drop-in installed and verified by SIGKILL test |

## Root cause

Four defects compounded. Only the first was a resource problem.

**1. No memory headroom.** bilby has 15.7 GB RAM and 8 GB swap, and swap was
already fully consumed before the build started — roughly 13.5 GB of
anonymous memory across 326 processes. With swap exhausted there is no
reclaim path, so the first workload to demand fresh unswappable pages
triggers a global OOM. The ESPHome build was an ordinary thing to run; it
only proved fatal because the other ~12 GB was already committed. 38
containers run without a memory limit, so nothing bounds the baseline.

**2. Victim selection freed almost nothing before it mattered.**
`user@.service` carries `OOMScoreAdjust=100` (systemd upstream default),
which on a 15.7 GB host adds ~1.57 GB of synthetic badness. That makes tiny
session processes rank above containers sitting at 0. The kernel killed six
processes; the first five freed ~13 MB combined, and the sixth
(`clickhouse-serv`, 884 MB) is what actually resolved the pressure.

This victim ordering is deliberate and stays: bilby exists to run the
containers, and an interactive session is the cheapest thing to lose. Worth
recording precisely though — the policy did **not** protect ClickHouse. It
added the session as an extra casualty *ahead* of the container, rather than
in place of it, because badness is scored per-process and session processes
are individually tiny.

**3. The user manager has no self-heal.** `user@.service` ships with no
`Restart=` because systemd-logind owns its lifecycle: logind starts it on a
user's first session and stops it after the last. If the manager is killed
while sessions are still open, logind still regards the user as active, no
"first session" event fires, and the failed unit is never restarted. Several
new SSH logins over the following 2h32m did not repair it. Every user
service under it stayed dead — most consequentially `machine-ssh-agent`,
which is the only path to SSH credentials on this host (no private keys on
disk), so bilby could not reach fractal, numbat or kangaroo.

This is the same shape as the 2026-06-16 finding: a component in a failed
terminal state that no mechanism is watching.

**4. fractal's Alloy wedged silently — a novel failure mode.** During the
edge disruption, fractal's Alloy exhausted its
`retry_on_failure { max_elapsed_time = "30m" }` budget and then stopped
exporting permanently, emitting no further log lines and opening no further
connections, while the container continued to report `healthy`.

The notable part is that `max_elapsed_time = "30m"` **is** the fix from the
2026-06-19 postmortem, introduced to replace an infinite-retry footgun that
turned a hung connection into a permanent wedge. Here the bounded retry
became the outage mechanism itself, converting a ~3-minute edge disruption
into a 2h41m silent stop. The configuration was correct and
`disable_keep_alives = true` was properly applied — this is not the
2026-06-19 bug recurring.

fractal's own monitoring gaps (no Gatus endpoints, incomplete healthchecks)
are **not** a finding here: fractal is mid-provisioning under the Ansible
host-provisioning migration and that coverage is not built yet. What is
notable is the Alloy failure mode, not fractal's general state.

## Impact

- **No data loss to any service or database.** No filesystem, backup, or
  NFS involvement.
- **Operator session destroyed.** tmux server, 5 fish shells, 4 `claude`
  sessions and a `docker` client SIGKILLed with no warning. Session state
  unrecoverable.
- **SSH from bilby unavailable for 2h32m** (13:32:45 → 16:02) to every
  other host, because the only credential path is the killed agent.
- **2h41m of fractal telemetry permanently lost** (13:32:47 → 16:14:10).
  fractal is a low-volume host, so the absolute volume is small, but the
  gap is total.
- **Container plane essentially unaffected.** `clickstack-clickhouse` and
  `pocket-id` restarted automatically within ~1 second and returned
  healthy. Log ingestion dipped 7% for a single 10-minute bucket
  (21,505 vs a ~23,100 baseline) and fully recovered in the next one.

## Resolution

**Host-persistent (bilby)**

- [x] **2026-08-08**: `user@1000.service` recovered with
  `systemctl reset-failed` + `start`; `machine-ssh-agent` restored with its
  PIV key.
- [x] **2026-08-08**: `user@.service.d/10-restart-on-failure.conf` drop-in —
  `Restart=on-failure`, `RestartSec=2s`, `StartLimitBurst=5` over 300 s.
  Verified by SIGKILLing the live manager: it returned in under 8 s
  (pid 4118673 → 4162008) and every session scope was untouched.
  `on-failure` rather than `always` so a clean logout is not restarted.
- [ ] Bound the memory baseline — 38 containers currently run uncapped.
- [ ] Evaluate enabling `systemd-oomd` for graceful pressure-based reclaim
  ahead of the kernel's blunt pass (currently inactive).

**In-repo**

- [x] **2026-08-08**: drop-in carried by the Ansible `base` role
  (`ansible/roles/base/`), so every provisioned host gets it rather than
  bilby alone — the defect is in systemd's session model, not in bilby.

**Operational**

- [x] **2026-08-08**: fractal Alloy restarted; ingestion verified
  end-to-end rather than by container health.
- [ ] Decide a durable fix for the Alloy wedge — the bounded retry needs to
  resume rather than stop permanently once its budget expires.

## What we learned

- **A bounded retry can be an outage mechanism, not just a safety valve.**
  The 30-minute cap was the correct fix for infinite retry, but nothing made
  the exporter resume afterwards. "Give up safely" and "recover" are
  different properties and the second was never implemented.
- **A healthcheck that probes a process's own admin port cannot see a dead
  data path.** fractal's Alloy reported `healthy` for the entire outage
  because its check hit `:12345`, which stays up regardless of whether
  anything is being exported. Verify a pipeline with a config-level or
  volume signal, never with container health.
- **`docker inspect … .State.OOMKilled` is false for a global OOM.** That
  flag only sets for *cgroup* OOM, and uncapped containers can never trip
  it. ClickHouse was unambiguously SIGKILLed by the kernel and still
  reported `OOMKilled=false`. Use `exitCode=137` in the docker daemon log.
- **Elevated `oom_score_adj` on small processes wastes kill cycles.** Five
  kills freed ~13 MB before the sixth freed 884 MB. Anything scored more
  killable should also be worth killing.
- **Absence of logs is not evidence of an outage on a low-volume host.**
  fractal's normal maximum daily gap is ~240 minutes, so its silence looked
  routine. Only injecting live traffic and watching for arrival settled it.

## Out of scope

- **Lowering `OOMScoreAdjust` on `user@1000.service`.** Deliberately not
  changed. The containers are the point of the host and an interactive
  session is the correct thing to sacrifice; see Root cause #2.
- **fractal's incomplete monitoring.** No Gatus endpoints and partial
  healthchecks are expected at fractal's current provisioning stage, tracked
  under the host-provisioning migration rather than here.
- **`nathanbaxter-deploy` failing since 2026-08-02** with
  `could not read Username for 'https://github.com'` — surfaced during this
  investigation, unrelated to the OOM, left for separate handling.

## Related

- [2026-06-19 — alloy-exporter-keepalive-wedge](2026-06-19-alloy-exporter-keepalive-wedge.md) — introduced the bounded retry implicated here
- [2026-06-16 — firmware-reboot-recovery](2026-06-16-firmware-reboot-recovery.md) — same "failed terminal state nothing watches" shape
- [2026-05-30 — power-outage-nfs-recovery](2026-05-30-power-outage-nfs-recovery.md) — the other bilby-wide recovery incident
- `ansible/roles/base/` — where the restart drop-in lives
- [Host provisioning](../host-provisioning.md) — fractal's provisioning status
