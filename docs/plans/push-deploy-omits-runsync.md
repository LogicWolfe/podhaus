# Known issue: push-to-deploy does not apply stack-definition changes

**One-line:** the `podhaus-push-deploy` procedure only *deploys*
stacks — it never runs a `RunSync` — so any change to a stack's
`environment` block (or any other stack **resource-definition** field)
in `*/stack.toml` is **invisible to the deploy until someone manually
RunSyncs the `podhaus` ResourceSync**. With fail-fast stacks this
silently crash-loops the stack on the next redeploy.

Status: open / by-design-but-sharp. Captured 2026-05-17 after it took
down live fenwick for ~30 min. Not yet fixed — options at the bottom.

## Symptom (what you will see)

You add or change a secret/env var in `<stack>/stack.toml`'s
`environment = """…"""` block (and the matching `${VAR}` in
`compose.yaml`), commit, and push. The GitHub push webhook fires,
`podhaus-push-deploy` runs, the stack redeploys "successfully"… and
the container comes up with the **old** environment — the new var is
**empty** (or, for a brand-new required var, the stack **crash-loops**
on its boot validation). Komodo shows the deploy as green. Nothing
errors. `GetStack` shows the stack's `config.environment` *without*
your new line.

## The worked scenario (fenwick `INTERNAL_HTTP_TOKEN`, 2026-05-17)

1. fenwick gained a **required** env var `INTERNAL_HTTP_TOKEN`
   (Phase 4 internal HTTP injection transport). fenwick fails its
   boot gate fast if it is absent — by design (a missing secret is a
   loud error, never a silently-disabled transport).
2. fenwick source is bind-mounted under `deno run --watch`, so the
   code went live on save → the live process immediately began
   crash-looping (`Invalid Fenwick environment: internalHttpToken`).
   Expected: the fix is to provision the var, not weaken the check.
3. Provisioned the secret correctly:
   - 1Password Homelab item **"Fenwick Internal Token"** → komodo-op
     → Komodo Variable `OP__KOMODO__FENWICK_INTERNAL_TOKEN__CREDENTIAL`
     (verified present, 64 chars). **The komodo-op secret sync worked
     fine — this is not a komodo-op problem.**
   - `fenwick/stack.toml`: added
     `FENWICK_INTERNAL_HTTP_TOKEN=[[OP__KOMODO__FENWICK_INTERNAL_TOKEN__CREDENTIAL]]`
     to the `environment` block.
   - `fenwick/compose.yaml`: added
     `INTERNAL_HTTP_TOKEN: ${FENWICK_INTERNAL_HTTP_TOKEN}`.
   - Committed + pushed podhaus.
4. The push webhook drove `podhaus-push-deploy` → fenwick redeployed.
   **The container recreated, but `INTERNAL_HTTP_TOKEN` was empty** →
   still crash-looping, now on `Too small: expected string to have
   >=1 characters`.
5. `GetStack fenwick` → `config.environment` **did not contain**
   `FENWICK_INTERNAL_HTTP_TOKEN`. The Komodo stack *resource* still
   held the pre-change env block, so `compose`'s
   `${FENWICK_INTERNAL_HTTP_TOKEN}` substituted to empty.
6. Recovery: `RunSync(podhaus)` **awaited to `Complete`**, then
   `DeployStack(fenwick)` **awaited to `Complete`**. Container came up
   healthy, token len 64, `/events` returns 401 unauthenticated
   (transport live). Total downtime ~30 min, almost all of it spent
   discovering that push-deploy doesn't RunSync.

## Root cause / mechanism

Komodo separates two things this repo's mental model tends to merge:

- **The Stack *resource definition*** — Komodo's stored copy of the
  stack, including the fully-formed `environment` block (with
  `[[OP__KOMODO__…]]` Variables already substitutable). This is
  populated **only by a ResourceSync run** reconciling
  `*/stack.toml` → the Komodo resource.
- **DeployStack** — renders `compose` using the **stored resource
  definition's** environment and `docker compose up`s it. It does
  **not** re-read `stack.toml` and does **not** RunSync.

So the chain is `stack.toml` → *(RunSync)* → Komodo Stack resource →
*(DeployStack)* → container env. `podhaus-push-deploy`
(`komodo/sync/procedures.toml`) is:

```
stage 1: BatchDeployStackIfChanged  pattern="*"
stage 2: BatchDeployStack           pattern="kangaroo-*"
```

— **no RunSync stage**. The push webhook therefore advances the second
arrow but never the first. `compose.yaml` content changes *are* picked
up (compose files are read at deploy from the on-host repo), which is
why this is so easy to miss — the `compose.yaml` half of a two-place
change applies, the `stack.toml` half does not, so the var resolves to
empty rather than erroring loudly at the compose layer.

Aggravating specifics:

- The `podhaus` ResourceSync has `config.managed = false` and **no git
  repo of its own** (`repo: ""`, `resource_path: ["."]`). It reads the
  sync/stack TOMLs straight off a **host bind**:
  `/home/nathan/repos/podhaus → /syncs/podhaus` in `komodo-core`. So
  the *files* Komodo would sync from are always current with the local
  working copy (even uncommitted!) — the staleness is **purely** the
  un-reconciled Komodo *resource definition*. `managed:false` also
  means Komodo never auto-applies the sync on a git change; an explicit
  `RunSync` is the *only* thing that reconciles stack defs.
- `RunSync` then `DeployStack` issued back-to-back **races**: the
  deploy can run against the still-stale resource def before the sync
  commits. The recovery must **await the RunSync update to `Complete`
  (poll `GetUpdate`) before** issuing `DeployStack`, and await that
  too. Fire-and-forget produces a green deploy with the old env.

## When this bites

Any change to a stack **resource-definition** field via the normal
git-push flow, in particular:

- Adding/renaming/removing an `environment` line in `*/stack.toml`
  (the common case — every new secret).
- Any other `[stack.config]` change (volumes-via-toml, server, etc.).

It is **worst with fail-fast stacks**: a newly-*required* env var
means the redeploy doesn't just run with stale config, it
**crash-loops** until a human knows to RunSync. This is the same
hazard the Bugsink runbook already flagged in the small
("validate a secret-bearing stack on a **redeploy**, not just first
deploy") — generalised: *validate stack-def changes by confirming the
Komodo resource updated, not just that the deploy went green.*

Pure `compose.yaml`-only changes are unaffected (read at deploy).
komodo-op Variable sync is unaffected (independent loop; it worked
correctly throughout the scenario above).

## Manual procedure until fixed

For any push that touches a `*/stack.toml` `environment`/resource def:

1. Push as normal.
2. `RunSync` the `podhaus` ResourceSync and **wait for the update to
   reach `Complete`** (poll `GetUpdate`, don't assume).
3. Confirm with `GetStack <stack>` that `config.environment` now
   contains the change.
4. `DeployStack <stack>` and wait for `Complete`.
5. Verify the container actually has the value (`docker inspect` env
   length / health), not just that Komodo reported success.

(Komodo API on `http://localhost:9120`, creds = 1Password
"Komodo API OnePassword Sync", `X-Api-Key`/`X-Api-Secret`.)

## Options to actually fix (decide later)

1. **Add a `RunSync(podhaus)` stage to `podhaus-push-deploy` before
   the deploy stage.** Most direct: the normal push flow then
   reconciles stack defs before deploying, matching everyone's mental
   model. Trade-off: every push now RunSyncs (cheap; the sync is a
   diff/apply over local files) and the procedure must order
   sync-before-deploy and not race (RunSync stage must complete before
   the deploy stage — Komodo runs stages sequentially, so a dedicated
   earlier stage is sufficient). Need to confirm a ResourceSync with
   `managed:false` still applies under a procedure `RunSync` execution
   (it does when invoked explicitly; verify in Komodo 1.19.5).
2. **Flip the `podhaus` ResourceSync to `managed:true`** so Komodo
   auto-reconciles stack defs on change, leaving push-deploy to only
   deploy. Trade-off: changes the repo's "nothing auto-applies without
   an explicit sync" posture; broader blast radius if a bad stack.toml
   lands.
3. **Formalise the manual step** (above) as the documented contract
   for env changes and leave the procedure alone. Cheapest, but
   relies on memory — exactly what bit us here.

Recommendation leans (1): smallest surprise, keeps the
explicit-sync-only posture for everything except the push path that a
human already intends as "apply my repo changes."

## Cross-references

- `docs/runbooks/bugsink.html` — the narrower "validate on a redeploy,
  not first deploy" lesson that this generalises.
- `komodo/sync/procedures.toml` — the `podhaus-push-deploy` procedure
  (the missing RunSync stage).
- `docs/komodo.html` — operating models / auto-deploy.
