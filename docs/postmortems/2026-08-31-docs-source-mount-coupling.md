# 2026-08-31 — Voltaire docs failed on a coupled repository mount

**Status:** Resolved  
**Severity:** Medium  
**Trigger:** Voltaire's docs stack could not satisfy its hard-coded nested chezmoi bind

## Summary

`voltaire.docs.pod.haus` stopped serving while the other docs instances remained
available. The stack treated the aggregate `~/repos` tree and chezmoi's canonical
checkout as mandatory Docker bind mounts in one container. Chezmoi's authoritative
location is `/home/nathan/.local/share/chezmoi`; a convenience symlink under
`~/repos` on another host had obscured that ownership boundary. When the nested
mount contract could not be satisfied on Voltaire, the whole docs instance was
unavailable even though the rest of its repositories were readable.

Removing the nested chezmoi bind from Voltaire's live stack restored service. The
lasting fix replaces per-checkout container mounts with Ansible-managed read-only
source slots. Docs-server discovers a typed catalog over the stable slot root,
serves every available source, and returns degraded health until every configured
source is present. Restart-based autoheal is deliberately disabled for source
degradation because a restart cannot restore a checkout.

Bilby's power outage on 2026-08-30 prompted the initial investigation but was not
the root cause. Voltaire's content and origin path are local to Voltaire and reach
Numbat through Voltaire's outbound relay.

## Timeline

| Time (AWST) | Event |
|---|---|
| 2026-08-30 | Bilby lost power. This was initially considered a possible dependency failure. |
| 2026-08-31, before 08:30 | `voltaire.docs.pod.haus` was observed not serving. The affected host was initially reported as Fractal and then corrected to Voltaire. |
| 08:31 | Voltaire's Docker journal recorded failed `docs` DNS lookups from the local origin path, confirming the request path reached the host but not a serving docs container. |
| Approximately 09:00 | Inspection isolated the hard nested chezmoi bind and confirmed `/home/nathan/.local/share/chezmoi` as the authoritative checkout. |
| 09:12 | The live Voltaire compose was corrected without the nested bind; Docker attached `docs` to `dockernet`, and the local health plus full mTLS origin probe returned 200. |
| 12:34–12:38 | Source adapters, aggregate health, partial serving, monitoring, and filename-derived navigation were committed and deployed. |
| 12:58 | Gatus reported successful Bilby, Fractal, and Voltaire docs checks. All three containers ran the same deployed revision and returned healthy source catalogs. |

## Root cause

The outage was the combination of three defects:

1. **Source topology was a container startup dependency.** Compose mounted the
   aggregate repository directory and then mounted chezmoi again beneath it. One
   unavailable or structurally incompatible checkout prevented the single
   container from serving unrelated repositories.
2. **Health and recovery described the wrong failure.** The health endpoint only
   proved that the process answered, while autoheal could only restart a running
   unhealthy container. Neither represented per-source availability, and a restart
   could not repair a host bind.
3. **Remote docs instances were not monitored.** Gatus had no source-aware checks
   for Fractal or Voltaire and no Periphery checks for either host, so the failure
   depended on a person opening the site.

Five whys:

1. Why was Voltaire docs unavailable? The docs container was not serving after its
   repository mounts could not all be satisfied.
2. Why did one repository prevent all docs from serving? Every checkout was encoded
   as a mandatory bind on the one container.
3. Why was checkout availability coupled to container creation? Compose owned both
   host discovery and application serving instead of consuming a stable host
   adapter contract.
4. Why did recovery not converge automatically? Autoheal only restarts running
   unhealthy containers, while the missing capability was restoring or withdrawing
   an unavailable host source.
5. Why was the mismatch not caught before the outage? There was no integration test
   for a missing source, no boot-time source adapter, and no remote docs health
   monitor.

The root cause was therefore not the preceding Bilby outage. It was a missing
source-isolation boundary, compounded by health and monitoring that described the
container rather than the complete source catalog.

## Impact

- `voltaire.docs.pod.haus` was unavailable until the live compose recovery.
- Bilby and Fractal documentation content was unaffected.
- No repository content was modified or lost.
- The canonical chezmoi checkout was never deleted; only the incorrect mount
  dependency and Fractal's obsolete convenience symlink were removed.

## Resolution

### Immediate recovery

- [x] **2026-08-31**: Removed the nested chezmoi bind from Voltaire's live docs compose and restored the container.
- [x] **2026-08-31**: Verified the local health endpoint and the Numbat-to-Voltaire mTLS origin path returned 200.

### Host source contract

- [x] **2026-08-31**: Added the `docs_sources` Ansible role for Bilby, Fractal, and Voltaire.
- [x] **2026-08-31**: Exposed the aggregate repository directory and canonical chezmoi checkout as independent read-only slots beneath `/opt/podhaus/docs-sources`.
- [x] **2026-08-31**: Made Docker require the shared source root at boot and added recurring source reconciliation for late checkouts.
- [x] **2026-08-31**: Verified the reconciler remounts a checkout replaced at the same path instead of trusting path text alone.
- [x] **2026-08-31**: Removed Fractal's obsolete `~/repos/chezmoi` symlink after verifying its canonical target.

### Application and deployment

- [x] **2026-08-31**: Replaced `REPOS_ROOT` with typed directory and named-repository sources.
- [x] **2026-08-31**: Kept available repositories serving while `/health` returns 503 for any unavailable source or name conflict.
- [x] **2026-08-31**: Ensured an available repository copy remains routable when a same-named configured source is unavailable.
- [x] **2026-08-31**: Isolated invalid dynamic repository names instead of allowing one filesystem entry to break the catalog.
- [x] **2026-08-31**: Removed docs-server's autoheal label and retained `unless-stopped` for process exits.
- [x] **2026-08-31**: Added Compose integration coverage for healthy, degraded, partial-serving, and recovered states.

### Monitoring and documentation

- [x] **2026-08-31**: Added Gatus checks for all three docs containers and Fractal/Voltaire Periphery reachability.
- [x] **2026-08-31**: Documented source ownership, degraded health, boot reconciliation, and the no-autoheal decision.
- [x] **2026-08-31**: Retired the completed single-root docs-server plan and removed its stale operational contract.

## What we learned

- Optional content must not be expressed as a mandatory container creation
  dependency when the product can usefully serve the remaining content.
- Health can remain strict without making serving all-or-nothing. A red aggregate
  signal and partial service are compatible.
- Autoheal is useful only when restarting can change the failed condition. A host
  checkout requires a host reconciler, not a container restart loop.
- Convenience symlinks are not infrastructure ownership. Source declarations use
  the authoritative checkout path on every host.
- A reconciler must validate the mounted object, not only the pathname recorded
  when it mounted it.

## Related

- [`docs/host-provisioning.md`](../host-provisioning.md) — source-slot ownership and operation
- [`docs/monitoring.html`](../monitoring.html) — aggregate docs health and alerting
- [`docs/architecture.html`](../architecture.html) — docs-server placement and source topology
- [`docs/postmortems/2026-05-30-power-outage-nfs-recovery.md`](2026-05-30-power-outage-nfs-recovery.md) — earlier boot-time mount and monitoring failure
