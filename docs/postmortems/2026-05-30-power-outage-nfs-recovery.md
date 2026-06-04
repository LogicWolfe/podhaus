# 2026-05-30 — Power-outage reboot left /mnt/jump unmounted; Gatus didn't notice

**Status:** Resolved
**Severity:** Medium
**Trigger:** household power outage → hard reboot of bilby

## Summary

A household power outage took bilby down. On reboot, dockerd hammered the
NFS automount units in the first ~5 seconds after `network-online.target`
fired but before the route to the QNAP (`10.0.0.25`) was usable.
`mnt-jump.automount` got six dockerd-triggered mount attempts in under a
second, blew through systemd's default `StartLimitBurst=5/10s`, and went
to permanently-failed state — systemd will never auto-retry a unit in
that state. `mnt-pouch.automount` happened to get only five attempts,
stayed under the limit, and recovered ~4 hours later when something
re-triggered the automount.

Four containers were left exited: `backrest`, `paperless`, `plex` (depend
on `/mnt/jump` directly or had Docker auto-create bind-source subdirs
under it), and `flood` (depends on `/mnt/pouch`, but its restart attempts
all landed inside the window where pouch was still down — docker's
restart backoff eventually gave up).

Gatus surfaced exactly one of the four as broken (`Backrest (bilby)`)
because that check is a direct dockernet probe (`http://backrest:9898/`).
The other three checks (`Paperless`, `Plex`, `Flood (Torrent)`) all hit
`https://<service>.pod.haus/`, which Cloudflare Access intercepts with a
`302 → login.cloudflareaccess.com` for unauthenticated requests. The
existing `[STATUS] < 400` condition accepted the 302 as healthy, so the
dashboard stayed green for ~14 hours despite the containers being dead.

Compounding that: even the one check that correctly went red
(`Backrest (bilby)`) didn't email — it had no `alerts:` block. Auditing
revealed that ~75% of Gatus endpoints had the same gap: only the
log-ingest staleness checks, Komodo Alerts, and the heartbeat endpoints
had ever been wired to email. The `*defaults` anchor that defined the
shared HTTP probe shape never included an alert.

## Timeline

| Time (AWST) | Event |
|---|---|
| 2026-05-30 ~19:35 | Household power outage. bilby goes hard-down mid-process; container exits all written with `FinishedAt=2026-05-30T11:35:32Z`. |
| 2026-05-30 ~20:08:49 | Power restored. bilby boots. |
| 2026-05-30 20:09:37 | `NetworkManager-wait-online` completes. Local IP up, but route to `10.0.0.25` not yet usable. |
| 2026-05-30 20:09:40 | dockerd starts, triggers automount for both NFS mounts. Six attempts on jump in <1 s → `mnt-jump.automount: Failed with result 'mount-start-limit-hit'`. Five attempts on pouch → automount stays in `running` state. |
| 2026-05-30 ~20:09–20:10 | Container restarts attempted for the four NFS-binding services; all fail at the OCI bind step with `no such device` / `host is down`. Docker backs off exponentially. |
| 2026-05-31 00:09:32 | Something accesses `/mnt/pouch` (likely a periodic cron or syncthing cross-LAN probe — not deterministically identified). Automount tries again, succeeds. Pouch becomes healthy. But the four containers are already in exit state with no further restart attempts. |
| 2026-05-31 ~09:45 | User notices Gatus shows Backrest (bilby) down, asks why no email arrived for it and what other state exists. |
| 2026-05-31 10:00 | `/mnt/jump` recovered via `systemctl reset-failed mnt-jump.automount && systemctl start mnt-jump.automount`. Four containers `docker start`-ed individually. All healthy within 30 s. |
| 2026-05-31 10:00 | Host-side systemd drop-ins installed (`bilby/host-systemd/install.sh`). |
| 2026-05-31 10:05 | Gatus rewritten to use internal probes for Access-fronted services + alerts wired into the `*defaults` anchor. |

## Root cause

Five layered defects, in order of how much they each contributed:

1. **`x-systemd.automount` has a permanent-failure mode for the boot-time
   rate-limit case.** systemd's default `StartLimitBurst=5/StartLimitIntervalSec=10s`
   trips with as few as six retries in one second. When dockerd is starting
   containers that bind the NFS mount path, each container start counts as
   one trigger. The number of triggers depends on how many containers bind
   that path — pouch had one fewer consumer than jump, so jump tripped and
   pouch didn't. Pure luck of the deck.

2. **`docker.service` is ordered `After=network-online.target` but the
   QNAP isn't necessarily reachable at that point.** `network-online.target`
   only proves the local interface is up; routing to `10.0.0.25` can lag by
   a few seconds (ARP, DHCP-driven routes, switch convergence, etc.). The
   first burst of automount triggers happens inside that window.

3. **Gatus's HTTP probes for Access-fronted services hit Cloudflare Access
   before reaching the backend.** Access intercepts unauthenticated requests
   with `302 → login.cloudflareaccess.com`. The shared `[STATUS] < 400`
   condition accepted that as healthy. Only services whose checks bypassed
   Access — direct dockernet probes (backrest), service-token bypass
   targets (storage.pod.haus health endpoints), or non-`*.pod.haus` paths
   (nathanbaxter.com) — could ever fail correctly.

4. **The `*defaults` anchor didn't include `alerts:`.** It carried
   `group`, `interval`, and `conditions`, so endpoints using `<<: *defaults`
   inherited the probe shape but not the alert wiring. Email alerting was
   only present on endpoints that declared `alerts:` by hand — log-ingest
   staleness, Komodo Alerts, and the heartbeats. Everything else was
   dashboard-only.

5. **Docker's restart-policy backoff effectively gave up.** With
   `restart: unless-stopped` and repeated OCI-level failures during the
   pouch-down window, the per-container backoff grew long enough that by
   the time pouch came back at 00:09:32 the next restart attempt was hours
   out. The four containers stayed exited indefinitely. This isn't strictly
   a defect — it's documented Docker behaviour — but it means the
   "containers self-heal when the mount comes back" reasoning fails.

The 2026-05-23 postmortem closed one layer of this problem (sentinel
healthchecks + `chattr +i` tripwires) but didn't address the boot-time
race, because the previous incident's root cause was post-OOM-reboot
with a different mount-failure timing.

## Impact

- **No data loss.** Plex's database, paperless's documents, backrest's
  restic repo — all untouched. The `chattr +i` tripwire on `/mnt/jump`
  did its job: every container that tried to auto-create a bind-source
  subdir under unmounted `/mnt/jump` failed at start instead of writing
  to local disk.
- **User-visible degradation:** Plex, Paperless, Flood, Backrest
  unavailable for ~14 hours. Backrest's nightly snapshot for the night
  of 2026-05-30 → 2026-05-31 did not run (container was exited at
  schedule time); the next run at 05:25 on 2026-05-31 succeeded after
  recovery.
- **Monitoring trust:** the dashboard showed green for ~14 hours on
  services that were actually dead. This is the more serious finding —
  the Plex/Paperless/Flood checks couldn't have failed at all under any
  failure mode that wasn't a tunnel outage.

## Resolution

### Host-level (bilby, persistent — installed via repo)

- [x] **2026-05-31**: `bilby/host-systemd/wait-for-qnap-nfs.service` — oneshot
  ordered between `network-online.target` and `docker.service` that polls
  TCP/2049 on the QNAP (max 180 s) before allowing dockerd to start. Best
  effort: if the QNAP stays unreachable, the service exits 0 anyway after
  the timeout so the host doesn't get stuck.
- [x] **2026-05-31**: `bilby/host-systemd/docker.service.d/10-wait-for-qnap.conf`
  drop-in: `After=wait-for-qnap-nfs.service`, `Wants=`.
- [x] **2026-05-31**: `bilby/host-systemd/mnt-pouch.automount.d/10-no-rate-limit.conf`
  and the matching `mnt-jump.automount.d/` drop-in: `StartLimitIntervalSec=0`,
  `StartLimitBurst=0`. Disables systemd's mount-retry rate limit on both
  automount units so even an unrecognised future burst pattern can't make
  the unit go to permanently-failed state — at worst the next access
  triggers a retry.
- [x] **2026-05-31**: `bilby/host-systemd/install.sh` idempotent installer.

### In-repo (Gatus)

- [x] **2026-05-31**: Every Access-fronted HTTP probe switched to an
  internal endpoint:
  - `HyperDX (ClickStack)` → `http://hyperdx:8080/`
  - `Home Assistant` → `http://172.18.0.1:8123/manifest.json`
  - `Kangaroo (NAS)` → `https://10.0.0.25/` + `client.insecure: true`
  - `Komodo` → `http://komodo-core:9120/version`
  - `Paperless` → `http://paperless:8000/` + `Host: paperless.pod.haus` header
  - `Plex` → `http://172.18.0.1:32400/identity`
  - `Syncthing` → reshaped to `InspectDockerContainer kangaroo/syncthing`
    via Komodo (kangaroo-resident, same pattern as Backrest kangaroo)
  - `Flood (Torrent)` → `http://flood:3000/`
- [x] **2026-05-31**: `*defaults` anchor now spreads `alerts: *alerts` so
  every endpoint using `<<: *defaults` automatically emails on failure.
- [x] **2026-05-31**: Explicit `alerts:` added to non-anchor endpoints
  that needed it: Mumble, both Periphery checks, Backrest (bilby) — the
  ASK from this incident — and Backrest (kangaroo). The three checks that
  already had `alerts:` (Komodo Alerts, two log-ingest staleness) kept
  their bespoke descriptions.

### Documentation (in-repo)

- [x] **2026-05-31**: This postmortem.
- [x] **2026-05-31**: `docs/postmortems/index.html` — table entry.
- [x] **2026-05-31**: `AGENTS.md` — Postmortems list entry; `bilby/host-systemd/`
  added to the key-files table.

### Recovery (operational)

- [x] **2026-05-31**: `systemctl reset-failed mnt-jump.automount && systemctl
  start mnt-jump.automount` to clear the permanent-failed state. Confirmed
  via `/mnt/jump/.podhaus-share-mounted` sentinel.
- [x] **2026-05-31**: `docker start plex paperless backrest flood` — all
  four recovered to healthy within 30 s.

## What we learned

- **Boot ordering against `network-online.target` proves the local
  interface is up, not that remote hosts are reachable.** Any service
  whose first action is to reach a LAN/cross-host peer needs an explicit
  reachability check (TCP-port probe in a oneshot), not a target
  dependency.

- **systemd's default rate limit on a network-mount automount is a
  permanent-failure footgun.** Five mount attempts in 10 s is trivially
  reachable by a normal dockerd container fanout at boot. Either raise
  it or disable it on any automount unit that backs an at-boot
  consumer. Don't think of the rate limit as a backstop — it's a tripwire
  into a state requiring manual intervention.

- **A monitoring check that hits an authenticating proxy can't detect
  backend failure.** The 302-from-Access pattern is the single most
  important class of false-green for any homelab using zero-trust
  ingress. Either probe the backend directly (dockernet, host
  network-mode via the bridge gateway, or Komodo's
  `InspectDockerContainer`), or supply credentials that let the probe
  through to the backend. A `[STATUS] < 400` condition is meaningful
  only when the request actually reaches the thing you're monitoring.

- **Default values shape behaviour more than per-endpoint config.** The
  `*defaults` anchor was the load-bearing decision for ~15 endpoints; it
  not including `alerts:` made the entire fleet's email coverage opt-in
  by oversight. When a default shape ships, every field it omits is a
  silent class of bug across every consumer.

- **Docker's `restart: unless-stopped` is not a substitute for
  fixing the underlying dependency.** A container that fails at OCI
  bind time will get backoff-throttled into a state where it won't
  restart for hours by the time the dependency recovers. Don't reason
  about restart policies as "self-healing"; they're "self-retrying with
  a cap".

## Out of scope

- **kangaroo's bilby-side health probe.** `Kangaroo (NAS)` now hits
  `https://10.0.0.25/` directly. If gatus on bilby and the QNAP both go
  down at once (e.g., a switch failure between them) the check goes red
  for the right reason — but if just the LAN path between dockernet and
  QNAP fails (route table corruption?), the check would say "kangaroo
  is down" when really it's "bilby can't see kangaroo". Acceptable
  trade for now; revisit if it false-fires.

- **Per-service Cloudflare Access service-token probes.** We could keep
  some checks hitting the public URL by adding `CF-Access-Client-Id` /
  `CF-Access-Client-Secret` headers (the Homelab service token already
  exists). Would give true end-to-end coverage at the cost of token
  management on the Gatus side. Not done in this remediation —
  internal probes are enough to catch backend death, which was the
  blind spot.

- **Audit of other automount units across the fleet.** kangaroo has its
  own QNAP-internal storage (not NFS-mounted); kookaburra has nothing.
  Only bilby's two mounts are at risk. If pinelake is added with NFS
  binds, the same host-systemd pattern applies — copy `bilby/host-systemd/`
  to `pinelake/host-systemd/` with the appropriate target IP.

## Related

- `bilby/host-systemd/` — the host-level systemd units this postmortem
  installs.
- `gatus/conf/config.yaml` — Gatus config with internal probes + default
  alerts.
- `docs/postmortems/2026-05-23-pouch-jump-mount-failure.md` — the prior
  NFS incident that introduced sentinel healthchecks + `chattr +i`
  tripwires. Those defences worked correctly during this incident
  (zero data loss); they covered the "container writes to local disk"
  failure mode, leaving the boot-time recovery failure mode unaddressed.
- `docs/stack-conventions.html` — NFS-bind healthcheck convention.
