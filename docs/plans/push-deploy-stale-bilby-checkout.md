# CRITICAL — push-to-deploy silently no-ops for pushes not made from bilby

## The defect

Every stage of `podhaus-push-deploy` reads from **bilby's working clone**
(`~/repos/podhaus`, bind-mounted into Komodo Core and bilby's Periphery)
— and nothing in the pipeline pulls that clone. The GitHub webhook fires,
the procedure runs all four stages, everything reports success, and the
push deploys **nothing**:

- Stage 0 `RunSync` reconciles stack defs and variables from the stale
  bind-mounted TOML.
- Stage 1 hashes stack directories from the stale tree, finds every
  running container's labels current, and force-deploys nothing.
- Stage 2 `BatchDeployStackIfChanged` diffs stale compose text against
  itself and no-ops.

Linked-repo hosts (kangaroo, numbat, fractal, voltaire) are *not* an
exception in practice: their Periphery clones only `git pull` during a
`DeployStack`, and no deploy is ever triggered because the triggering
decisions are all made from bilby's stale view.

## Why this was invisible until 2026-08-11

Every push historically originated **on bilby**, so its working clone was
at HEAD by construction the moment the webhook fired. The defect became
reachable when fractal and voltaire became first-class dev machines.

Discovered when a Pomerium SSH key registration pushed from voltaire
(`9aad953`) ran the full webhook procedure at 13:28 and deployed nothing
— the only symptom was a missing ssh-auth-notify Signal push, while both
numbat containers sat untouched at "Up 43 hours". Every push from a
non-bilby machine before the fix has the same exposure: **a green
webhook run is not evidence anything deployed.**

## Interim operating rule (until the fix lands)

After any push from a machine that is not bilby:

```
ssh bilby.pod.haus 'cd ~/repos/podhaus && git pull --ff-only'
ssh bilby.pod.haus 'cd ~/repos/podhaus && fish -lc ./komodo-sync'
```

Or make the push from bilby. Agents: treat this as part of the push
itself, not an optional follow-up.

## Fix options (deliberately not chosen yet)

- [ ] Decide and implement one of:
  - **(a) Pull step in the pipeline.** A stage before Stage 0 that
    fast-forwards bilby's clone. Komodo has no execution type that runs
    a command against an arbitrary host path; would need an Action that
    reaches bilby's Periphery (or a git sidecar), and must handle a
    dirty working tree (it is Nathan's live checkout) by refusing
    loudly, not stashing.
  - **(b) Retire bilby's files_on_host mode.** Give bilby a
    Komodo-managed linked-repo clone like every other host, so
    `DeployStack` owns the pull. Ends bilby's special status; migration
    touches every bilby `stack.toml` (`run_directory` →
    `linked_repo`), and the ResourceSync + hash Action need a
    Core-visible clone that updates on sync rather than the bind-mounted
    working copy.
  - **(c) Host-side pull-on-push.** A bilby webhook receiver or ofelia
    job that pulls the working clone. Cheapest, but adds a moving part
    outside Komodo and races the procedure unless ordered before it.
- [ ] Whichever lands: the same rot applies to the **fenwick / pets /
  docs-server** procedures only via `komodo/sync/*.toml` definitions
  (their build contexts are Komodo-managed clones); verify their Stage 0
  reads after the fix.
- [ ] Fold the resulting behaviour into `docs/komodo.html` and delete
  this plan.
