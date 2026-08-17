# Deploy-tree split: fix push-to-deploy's stale-bilby-checkout defect

## Status

Design chosen and implementation in flight on branch `deploy-tree-split`.
The old defect description is preserved at the bottom. **The interim
operating rule (ssh to bilby + pull + komodo-sync after any non-bilby
push) stays in force until the cutover checklist below is complete.**

## The two goals

1. **Push from any machine deploys latest `origin/main`.** Bilby's
   working checkout (`~/repos/podhaus`) must never be merged, pulled, or
   otherwise touched by the pipeline — it may hold in-progress work.
2. **`./komodo-sync` on bilby deploys the local checkout** (including
   uncommitted files), regardless of what's on main — the existing
   debug-iteration workflow, preserved.

No single tree can satisfy both, so the design separates them.

## Design: a Komodo-owned deploy tree with two feeders

Bilby gets a Komodo-managed clone of podhaus — the **deploy tree** — at
`/etc/komodo/repos/podhaus-deploy` (a native `Repo` resource, exactly
like kangaroo/numbat/fractal/voltaire already have). Every deploy-side
consumer reads it. The two entrypoints differ only in how they feed it:

- **Webhook push**: a new first stage `PullRepo podhaus-deploy` forces
  the tree to `origin/main`. Komodo's pull (verified in source,
  `lib/git/src/pull.rs`) is `git fetch --all --prune` →
  `git checkout -f <branch>` (discards tracked-file modifications) →
  `git pull --rebase --force`; an `on_pull = "git clean -fd"` hook
  removes untracked non-ignored leftovers, so after every pull the tree
  is exactly main (ignored files like deploy-written `.env` survive).
- **`komodo-sync`**: a new Komodo Action `podhaus-load-local-tree`
  (runs in Core, like the hash action) mirrors the working clone's
  current state — tracked + untracked-unignored files, enumerated via
  `git ls-files --cached --others --exclude-standard` — into the deploy
  tree, from a new read-only bind of the checkout.

Both feeders run as root inside containers, so the deploy tree is
root-owned and nothing on the host ever needs to write it. Last writer
wins in both directions: a push after a WIP `komodo-sync` reverts the
fleet to main (compose text / hashes differ again → Stage 1/2 redeploy);
a `komodo-sync` after a push overlays local state. Deterministic and
visible.

The deploy pipeline itself becomes source-agnostic: the current four
stages (RunSync → hash-inject/reconcile → BatchDeployStackIfChanged →
ofelia restart) move unchanged into a new procedure `podhaus-deploy`
("deploy whatever the deploy tree holds"). `podhaus-push-deploy` keeps
its name — so the GitHub webhook URL in `terraform/github.tf` is
untouched — and becomes: Stage 0 `PullRepo podhaus-deploy`, Stage 1
`RunProcedure podhaus-deploy`.

## Consumers repointed (the whole migration surface)

Three mounts/variables currently smear "the deploy source" across
bilby's working clone; all three repoint to the deploy tree:

| Consumer | Today | After |
|---|---|---|
| Komodo Core bind `/syncs/podhaus` (ResourceSync + hash action read it) | `${COMPOSE_KOMODO_REPO_PATH}` = working clone | `/etc/komodo/repos/podhaus-deploy` |
| bilby Periphery bind `/etc/komodo/repo` (27 files_on_host `run_directory`s) | working clone | `/etc/komodo/repos/podhaus-deploy` |
| `PODHAUS_REPO` Komodo Variable (container bind mounts) | host-discovered `$PWD`, seeded by komodo-start | fixed `/etc/komodo/repos/podhaus-deploy`, declared in `komodo/sync/variables.toml` |

Because the Periphery alias bind keeps `/etc/komodo/repo` as the
in-container path, **no stack.toml `run_directory` changes** and the
hash action's `stackRelToRepo()` prefix mapping is untouched. Core
additionally gains a read-only bind of the working clone at
`/syncs/podhaus-local` for the local feeder action.

### The one read-write exception: Home Assistant

Every `${PODHAUS_REPO}` bind in the repo is `:ro` except
`home-assistant/compose.yaml` — `${PODHAUS_REPO}/home-assistant/config:
/config/podhaus:z` is deliberately writable: HA's UI editor saves
automations/scenes/scripts through it into the checkout for committing.
Pointing that at a pull-reset tree would silently destroy UI edits. So
HA keeps a live working-clone bind via a new variable
`PODHAUS_CHECKOUT` (host-discovered, seeded by komodo-start = `$PWD`,
replacing the old `PODHAUS_REPO` seed). HA joins fenwick live-reload
and the docs-server `~/repos` bind as a documented "live from checkout"
exception.

## What each file changes

- `komodo/sync/repos.toml`: new `[[repo]] podhaus-deploy` — server
  `"podhaus"` (= bilby), `git_provider "github.com"`, `git_account
  "LogicWolfe"`, `repo "LogicWolfe/podhaus"`, `branch "main"`,
  `on_pull.command = "git clean -fd"`. No `path` override → Periphery
  clones to `${root_directory}/repos/podhaus-deploy` =
  `/etc/komodo/repos/podhaus-deploy` (identity bind, host path ==
  container path). Credentials come from the existing central
  `[[git_providers]]` block (komodo/core.config.toml.tmpl) that already
  serves bilby's fenwick/pets/docs-server linked repos.
- `komodo/sync/procedures.toml`: split as described above. The hash
  action's repo allowlist (`podhaus` / `podhaus-*` name prefix in
  actions.toml) already matches `podhaus-deploy`; no action change
  needed for that.
- `komodo/sync/actions.toml`: new `podhaus-load-local-tree` action.
  Enumerate the checkout via git (with `-c
  safe.directory=/syncs/podhaus-local` — the mount is nathan-owned,
  Core runs as root); enumerate the deploy tree the same way (it is a
  real clone, root-owned, no flag needed); copy the checkout set in
  (`Deno.copyFile` preserves the executable bit), delete deploy-tree
  files present in its own enumeration but absent from the checkout's,
  never touching `.git/` or git-ignored files (`.env` is deploy-written
  and must survive). Skip checkout-enumerated paths whose file is
  missing on disk (deleted-but-still-indexed). Fail loudly if the
  deploy tree has no `.git` (bootstrap not run).
- `komodo-sync`: new first step `RunAction podhaus-load-local-tree`
  (before the out-of-procedure RunSync, which must read the overlaid
  tree); `run_procedure podhaus-push-deploy` becomes `run_procedure
  podhaus-deploy` (skipping the pull stage — that's the whole point).
  fenwick/pets/docs procedure invocations unchanged.
- `komodo/ferretdb.compose.yaml`: repoint Core's `/syncs/podhaus` and
  Periphery's `/etc/komodo/repo` binds at
  `/etc/komodo/repos/podhaus-deploy`; add
  `${COMPOSE_KOMODO_REPO_PATH}:/syncs/podhaus-local:ro` to Core.
  `COMPOSE_KOMODO_REPO_PATH` (= `$PWD` of komodo-start) keeps the
  `komodo/.runtime:/config/runtime` bind.
- `komodo-start`: seed `PODHAUS_CHECKOUT` (= `$PWD`) instead of
  `PODHAUS_REPO`; new bootstrap step after Core is ready and before
  the first RunSync — idempotent `CreateRepo podhaus-deploy` (exists
  check first, mirroring the CreateResourceSync pattern) + `PullRepo`
  + poll to completion, so `/syncs/podhaus` is populated before the
  sync that reads it. The later RunSync adopts/reconciles the repo
  resource by name from repos.toml.
- `komodo/sync/variables.toml`: `PODHAUS_REPO =
  "/etc/komodo/repos/podhaus-deploy"` (fixed path, no longer
  host-discovered).
- `home-assistant/compose.yaml` + `home-assistant/stack.toml`:
  `${PODHAUS_REPO}` → `${PODHAUS_CHECKOUT}` for the config bind;
  env mapping `PODHAUS_REPO=[[PODHAUS_REPO]]` →
  `PODHAUS_CHECKOUT=[[PODHAUS_CHECKOUT]]`.
- `AGENTS.md` + `docs/komodo.html` + `docs/secrets.html` +
  `docs/stack-conventions.html`: reflect the new flow (docs slice).

## Semantics, edges, accepted limitations

- Pushing **from bilby** also goes through the deploy tree — bilby
  loses its special status; the interim ssh-and-pull rule dies.
- Peer agents' dirty files in the shared checkout no longer
  force-redeploy on every push; a half-saved editor buffer can never
  land in a running container (except HA's live config, by design).
- `komodo-sync` with local WIP on a **linked-repo host's** stack
  (kangaroo/numbat/fractal/voltaire) still deploys that host's clone
  at main — only defs/env/hashes reflect local state. Unchanged from
  today; accepted.
- If main gains a file at the same path as an untracked stray from an
  abandoned local overlay, `git pull --rebase` fails loudly; recovery
  is one `komodo-sync` or a manual clean of the deploy tree. Rare,
  fail-fast, accepted.
- The procedures.toml busy-guard caveat is unchanged: a push that edits
  procedure definitions still needs a follow-up `./komodo-sync` (its
  out-of-procedure RunSync applies the change).
- Secret rotations / variables.toml changes still don't auto-redeploy
  (hash excludes `.env`) — unchanged, deliberate.
- Stale Komodo-written `.env` files littering the working checkout
  become inert after cutover; optional cleanup.

## Cutover checklist (requires explicit go-ahead; order matters)

- [ ] Merge `deploy-tree-split` to main in `~/repos/podhaus` (bilby)
      and push from bilby. The old pipeline reads the (now-current)
      working clone; its first stage (the interim
      `podhaus-assert-fresh-checkout` guard) passes because the push
      came from bilby, then the RunSync stage aborts per the busy-guard
      caveat (the push touches procedures.toml) — expected.
- [ ] Direct out-of-procedure sync to land all definition changes:
      the `run_sync podhaus` step of the OLD komodo-sync, or curl
      `RunSync`. This creates the `podhaus-deploy` Repo resource, the
      `podhaus-load-local-tree` action, the `podhaus-deploy` procedure,
      updates `podhaus-push-deploy`, and sets the new `PODHAUS_REPO` /
      `PODHAUS_CHECKOUT` variable values (verify the sync overwrote the
      previously seeded `PODHAUS_REPO`).
- [ ] Delete the orphaned `podhaus-assert-fresh-checkout` Action via
      the API (`DeleteAction`). The podhaus sync runs `delete: false`,
      so dropping it from actions.toml does NOT prune the resource —
      and it carries `failure_alert = true`, so a zombie is future
      noise.
- [ ] Run the new `./komodo-start`: recreates Core + Periphery with the
      new binds, runs the CreateRepo/PullRepo bootstrap → deploy tree
      exists at main.
- [ ] One-time `BatchDeployStack "*"` (curl or UI): the `PODHAUS_REPO`
      value change alters no hash and no compose text, so nothing
      redeploys on its own; every stack must recreate once to pick up
      deploy-tree bind sources. Schedule for the 04:00 dead-time window
      or accept the brief fleet restart.
- [ ] Verify goal 1: from a non-bilby machine, push a trivial in-stack
      change; confirm the stack redeploys (config-level signal: new
      `podhaus.stack-content-hash` label on the running container) and
      `~/repos/podhaus` on bilby is untouched.
- [ ] Verify goal 2: uncommitted local edit on bilby + `./komodo-sync`
      → deploys; then push an unrelated change → stack reverts to main.
- [ ] Verify HA UI automation edits still land in the checkout.
- [ ] Delete the interim operating rule from AGENTS.md; fold the final
      behaviour into `docs/komodo.html`; trim this plan to nothing and
      delete it.

---

## Historical: the original defect (context for the design above)

Every stage of `podhaus-push-deploy` read **bilby's working clone**
(`~/repos/podhaus`, bind-mounted into Komodo Core and bilby's
Periphery) — and nothing in the pipeline pulled it. A push from any
other machine ran the webhook procedure green against a stale tree and
deployed nothing: Stage 0 reconciled stale TOML, Stage 1 hashed stale
directories (all labels "current"), Stage 2 diffed stale compose text
against itself. Linked-repo hosts were no exception in practice — their
clones only pull during a `DeployStack`, and no deploy was ever
triggered because the triggering decisions came from bilby's stale
view. Invisible until 2026-08-11 because every push historically
originated on bilby; surfaced when a Pomerium SSH key registration
pushed from voltaire (`9aad953`) deployed nothing.

From 2026-08-16 until cutover, an interim fail-closed guard
(`podhaus-assert-fresh-checkout`, first stage of `podhaus-push-deploy`)
made stale-checkout violations loud by asserting bilby's checkout HEAD
equalled GitHub main; the deploy-tree split removes it.
