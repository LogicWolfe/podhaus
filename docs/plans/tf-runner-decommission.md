# Decommission the `tf` runner → stock Terraform + chezmoi creds

> **DONE (2026-05-19), but built differently than planned below.** The
> runner was decommissioned and Terraform now runs stock from any
> machine — but the backend is the public `https://storage.pod.haus`
> (MinIO behind Caddy + a UniFi port-forward), *not* a loopback/VPN
> path; Cloudflare's proxy mangles SigV4 and can't be used. This
> document is planning history. **As-built record:**
> [MinIO public access via Caddy + UniFi](minio-public-caddy.md).

## Status

**NOT STARTED.** This is a prerequisite plan. The MinIO-exposure /
Publii work is **blocked on this** and resumes once the clean
foundation is in place. Planning only — nothing changed.

## Context

`/home/nathan/repos/podhaus/tf` is a 47-line bash wrapper:
`op run --env-file=.env -- docker run --rm --network dockernet -v
$PWD:/workspace … hashicorp/terraform:latest "$@"`. It bundles three
concerns: (1) reach the MinIO Terraform **state backend**
(`http://minio:9000`, resolvable only on `dockernet`), (2) inject
1Password secrets via `op run` (never written to disk), (3) pin the
Terraform toolchain via a Docker image (no host install).

It was accepted because it worked, but it's bespoke glue around things
Terraform supports natively. Concern (1) is the crux: the state
backend is dockernet-only. The from-anywhere requirement means the fix
is **not** "run on bilby via loopback" — it is to make the backend
reachable from anywhere, i.e. point it at the **public S3 endpoint**
(`https://storage.pod.haus`) that the MinIO-exposure plan creates. So
the sequencing **inverts** (see *Ordering*): MinIO S3 exposure is now
an upstream prerequisite, bootstrapped with the *current* `tf` runner
(which still works today), after which the backend is repointed and
the runner deleted. With (1) handled that way, (2) and (3) have stock
answers.

**Decision (user):** drive credential injection with **chezmoi** —
consistent with the existing chezmoi-managed `~/.claude.json` precedent
(`docs/monitoring.html`) — using the mechanism Terraform best supports
(environment variables; `~/.aws/credentials` is the only native file
and only covers the S3 backend, so env vars are the universal answer).

## HARD ARCHITECTURAL REQUIREMENT

**podhaus Terraform MUST be runnable from any machine.** The contract:
*clone podhaus + have chezmoi-provisioned Terraform creds ⇒ `terraform`
runs.* No host-pinned backend endpoint, no LAN-only provider, no
dockernet assumption in any from-anywhere root. This is a standing
constraint, not a one-off — **it must be added to `AGENTS.md` "Hard
rules" and `docs/terraform.html`** as part of execution (see
Components), so future TF changes are held to it.

Implication: this plan is **no longer "Terraform runs on bilby."** The
earlier `127.0.0.1:9000` direction is withdrawn — it violates the
requirement.

## Goal

Delete the `tf` script. Run **stock `terraform` from any machine**.
Creds from 1Password via the chezmoi-rendered env file (per-machine
`chezmoi apply`). Zero resource drift — tooling/plumbing only, no
infrastructure changes.

## Reviewed chezmoi setup (ground truth, not assumed)

Inspected the live system, not the docs:

- chezmoi v2.70.0, source repo **`~/.local/share/chezmoi`** — a
  **separate git repo** from podhaus (clean working tree, auto-updates
  via `chezmoi-autoupdate.fish`). **This decommission spans two repos.**
- Host is **bilby** (`bilby.pod`, Fedora Asahi aarch64), **fish** shell,
  `op` CLI v2.33.1 installed from the official 1Password dnf repo by
  `run_onchange_04-packages.sh.tmpl`.
- `.chezmoi.toml.tmpl` sets `has1Password` from the **1Password desktop
  *agent socket*** (`~/.1password/agent.sock`) — false on headless
  bilby. It only gates a (currently empty) `secrets.fish`. It does
  **not** gate chezmoi's `op` use: `modify_dot_claude.json.tmpl`
  already resolves `op://Homelab/...` via `onepasswordRead "<ref>"
  "my.1password.com"` at apply time and renders the real secrets into
  `~/.claude.json`. So **apply-time `onepasswordRead`→disk is an
  established, accepted pattern here** for convenience tokens.
- A second, more careful pattern exists for **high-value** secrets:
  `op-ssh-key.fish` / `op-unlock.fish` / `op-ensure.fish` do **runtime
  `op read`** into a transient temp file / agent, **never persisted**.
- **Terraform is already chezmoi-managed** in
  `run_onchange_04-packages.sh.tmpl`: macOS installs via
  `hashicorp/tap` with the explicit comment *"community formula is
  stuck at 1.5.7"* (the no-frozen-version rule is already enforced
  here); the generic-Linux branch uses the HashiCorp **apt** repo.
  **bilby hits the separate Fedora branch, which installs
  `1password-cli` from its official dnf repo and has _no terraform at
  all_.** That gap is the real "install Terraform" work.
- **Off-limits — these are the user's *work* setup, not podhaus:**
  `dot_aws/config` (Switch Batteries AWS SSO profiles `sb-legacy`/
  `sb-modern`), and the `terraform.fish` / `tf-dev.fish` /
  `tf-prod.fish` functions (git-branch + `terraform workspace`
  discipline for that org). Do not repurpose `~/.aws/config` and do not
  reuse those function names. `terraform.fish` only blocks dirs whose
  `*.tf` contains `terraform.workspace`; podhaus uses per-root state
  keys, not workspaces, so it passes through (verify with a grep).

## From-anywhere review — blockers found in live config

Reviewed actual `cloudflare/` usage against the hard requirement:

- **State backend (BLOCKER).** `backend.tf:28`
  `endpoints.s3 = "http://minio:9000"` — dockernet/bilby-only.
  **Fix:** repoint to the public S3 endpoint
  `https://storage.pod.haus` (created by the MinIO-exposure plan).
  Drives the ordering inversion below.
- **UniFi provider (BLOCKER).** `providers.tf:10`
  `provider "unifi" { api_url = "https://10.0.0.1" }`, used by
  `unifi_dns_record` resources in `dns_unifi_split_horizon.tf`
  (`unifi.pod.haus`→10.0.0.1, `bilby.pod.haus`→10.0.0.119
  split-horizon LAN DNS). A hardcoded LAN IP — off-LAN it fails
  refresh/plan and **takes the whole root down**, even with creds +
  public backend. **Fix (near-free, no root split):** `module "unifi"`
  already publishes `unifi.pod.haus` → `https://10.0.0.1:443` through
  the tunnel (`origin_request.no_tls_verify`, Access policy
  `unifi_bypass` = everyone — "UniFi has its own login"). Repoint the
  provider to `api_url = "https://unifi.pod.haus"`. Works from
  anywhere; the controller is **already tunnel-public today**, so this
  is *no posture change*. The `unifi_dns_record` resources then manage
  fine remotely. `allow_insecure = true` can likely be dropped (the
  provider now hits a valid Cloudflare edge cert) — tighten and
  verify. Also fix the stale `providers.tf` comment claiming
  `api_url` comes from `UNIFI_API_URL` env (it's hardcoded; the `tf`
  runner only ever forwarded `UNIFI_API_KEY`).
- **Cloudflare + GitHub providers — OK.** `api.cloudflare.com` /
  `github.com` are public; reachable from anywhere already.
- **Splitting UniFi into its own root — rejected *for the network
  reachability problem* (repointing to `unifi.pod.haus` solves that
  with one line; a split is needless abstraction — favor simplicity).
  But see component 7:** the split is *conditionally reopened* on a
  different axis — if `ubiquiti-community/unifi` (community fork) has
  no published build for a target operator platform (e.g.
  `darwin_arm64`), the `cloudflare/` root can't `init` there at all,
  and splitting becomes the way to keep the main root from-anywhere.
  Decide on the registry's actual platform list, not assumption.

### Ordering (inverted from the earlier draft)

1. **Bootstrap with the *current* `tf` runner** (works today,
   dockernet→`minio:9000`): apply the MinIO-exposure plan's Cloudflare
   part — `storage.pod.haus` S3 ingress + WAF. (User-authorized
   `apply`.) The runner bootstraps its own replacement's prerequisite.
2. **This plan:** repoint `backend.tf` → `https://storage.pod.haus`
   and `providers.tf` unifi → `https://unifi.pod.haus`; install stock
   Terraform via chezmoi; chezmoi-rendered creds; **gitignore the
   lockfile** (no committed lock — component 7); delete `tf`; add the
   hard rule to `AGENTS.md`/`docs/terraform.html`.
3. **Verify from a non-bilby machine** (the acceptance test).
4. Resume the rest of the MinIO/Publii plan (`minio/terraform/` buckets) —
   stock `terraform`, backend also `https://storage.pod.haus`,
   from anywhere.

No cycle: step 1's tool is deleted only in step 2, *after* it has
produced the public endpoint step 2 depends on.

## Approach

### Credential mechanism — chezmoi-rendered fish env file, secrets at rest, NO wrapper

**Decision (user):** credentials persist to disk; `terraform` is run
**directly** (`cd cloudflare && terraform plan`) — no wrapper, no
function, no per-invocation `op`. This is the `modify_dot_claude`
pattern (chezmoi `onepasswordRead` → real values on disk), which is
already the accepted norm here for homelab creds; the at-rest
trade-off is explicitly chosen and not relitigated.

Add **one chezmoi-managed fish `conf.d` file** —
`~/.config/fish/conf.d/podhaus-tf.fish`, source
`private_…/fish/conf.d/podhaus-tf.fish.tmpl` (the `private_` prefix →
chezmoi writes it `0600`). It is auto-sourced by every fish shell, so
the env vars Terraform reads natively are simply present — zero
wrapper. The template body is `set -gx` exports whose values come from
`onepasswordRead "<ref>" "my.1password.com"` (identical mechanism and
account to `modify_dot_claude.json.tmpl`):

```
set -gx AWS_ACCESS_KEY_ID        {{ onepasswordRead "op://Homelab/MinIO Terraform User/username" "my.1password.com" }}
set -gx AWS_SECRET_ACCESS_KEY    {{ onepasswordRead "op://Homelab/MinIO Terraform User/credential" "my.1password.com" }}
set -gx CLOUDFLARE_API_TOKEN     {{ onepasswordRead "op://Homelab/Cloudflare API Token/credential" "my.1password.com" }}
set -gx UNIFI_API_KEY            {{ onepasswordRead "op://Homelab/UniFi API Key/credential" "my.1password.com" }}
set -gx GITHUB_TOKEN             {{ onepasswordRead "op://Homelab/Homelab GitHub Personal Access Token/token" "my.1password.com" }}
set -gx TF_VAR_komodo_webhook_secret {{ onepasswordRead "op://Homelab/Komodo Webhook Secret/password" "my.1password.com" }}
```

Use the **exact op:// refs from the current `cloudflare/.env`** — copy,
don't retype. Properties:

- **No wrapper / no function** — `terraform` works directly in any TF
  root; these env vars are what Terraform's S3 backend + Cloudflare/
  UniFi/GitHub providers + the `komodo_webhook_secret` TF var read
  natively. Nothing else to learn or invoke.
- **Persisted, not per-invocation** — values are written at
  `chezmoi apply` time and just sit there; `op` is touched only when
  `chezmoi apply` re-renders (same as `~/.claude.json` today), not on
  every `terraform` run. Rotation: rotate in 1Password → `chezmoi
  apply`.
- **Source has no secrets** — the chezmoi git repo holds only the
  `op://` refs (the one good property we keep); the rendered
  `~/.config/fish/conf.d/podhaus-tf.fish` holds real values at `0600`,
  consistent with `~/.claude.json`.
- **Naming** — call it `podhaus-tf.fish`, *not* `secrets.fish`
  (`.chezmoiignore` drops `conf.d/secrets.fish` when `not
  .has1Password`, which is bilby's case; a distinct name avoids that
  gate while `onepasswordRead` still works on bilby, as
  `modify_dot_claude` proves).

> Known property, not a blocker: a `conf.d` file exports these in
> *every* fish shell, not only podhaus work. Acceptable for a
> single-operator homelab box and the price of "no wrapper." If
> ever undesirable, the same file can move behind an explicit
> `source` — but the user wants it ambient, so leave it ambient.

### Components to change

**chezmoi dotfiles repo (`~/.local/share/chezmoi`):**

1. **Terraform install — add a Fedora branch.** In
   `run_onchange_04-packages.sh.tmpl`, add to the **Fedora elif**
   (where `1password-cli` is installed) a block installing **official
   HashiCorp Terraform** from the HashiCorp **rpm** repo
   (`rpm.releases.hashicorp.com` / `yum.releases.hashicorp.com`),
   mirroring the existing official-dnf-repo block pattern. Explicitly
   **not** Fedora's repos (dropped Terraform post-BSL-relicense),
   **not** OpenTofu, **not** the frozen final-MPL `1.5.x` — same
   principle the macOS branch's own `1.5.7` comment already states.
   This matches `hashicorp/terraform:latest` (official latest BSL) that
   the `tf` wrapper uses today, so the **state format** stays
   compatible (no committed lockfile to reconcile — component 7).
2. **Add the chezmoi-rendered `conf.d/podhaus-tf.fish` env file** per
   the credential mechanism above (`private_…/fish/conf.d/
   podhaus-tf.fish.tmpl`, `onepasswordRead`). No function, no wrapper.

**podhaus repo:**

3. **Backend endpoint → public.** `cloudflare/backend.tf`:
   `endpoints.s3` `http://minio:9000` → **`https://storage.pod.haus`**
   (the from-anywhere endpoint; prerequisite applied in Ordering
   step 1). Bucket `terraform-state`, key `cloudflare.tfstate`,
   `use_path_style`, all `skip_*` flags **unchanged**. Needs
   `terraform init -reconfigure`; state content/location identical →
   **no state migration/move** (decline any migrate prompt). The
   backend's `AWS_*` creds (MinIO Terraform User) come from the chezmoi
   env file and authenticate over the public endpoint the same as over
   dockernet (S3 SigV4 — Terraform's state ops are plain S3 object
   calls, not under `/minio/admin/`, so the WAF block doesn't touch
   them; no rate-limit exists).
4. **UniFi provider → public.** `cloudflare/providers.tf`:
   `api_url = "https://10.0.0.1"` → **`"https://unifi.pod.haus"`**
   (already tunnel-published by `module "unifi"`). Drop
   `allow_insecure = true` (now a valid CF edge cert — verify the
   provider connects cleanly without it; keep only if it complains).
   Delete the stale comment about `UNIFI_API_URL`/`UNIFI_INSECURE`
   env. `UNIFI_API_KEY` still comes from the chezmoi env file.
5. **Delete `tf`** and fix references to **direct `terraform`**
   (`cd cloudflare && terraform plan` — env from the conf.d file):
   - `AGENTS.md` — Key-files table row; the `cd cloudflare && op run
     --env-file=.env -- ../tf apply` line (≈L166) → `cd cloudflare &&
     terraform apply`; the push / `tf apply` auth-gating notes
     (≈L234-245). **The authorization hard rule stays verbatim — only
     the command spelling changes.**
   - `cloudflare/README.md` (L38-43, L91); `docs/terraform.html`
     (L80, 103-104, 151, 170-193); `docs/networking.html` (L77,
     163-164); `docs/disaster-recovery.html` (L90). **Auth source
     changes:** Terraform creds now come from chezmoi `onepasswordRead`
     (the `my` 1Password account, at `chezmoi apply` time) — *not* the
     repo-root `OP_SERVICE_ACCOUNT_TOKEN`. Before touching the
     `OP_SERVICE_ACCOUNT_TOKEN` setup at disaster-recovery L59-60,
     **check for other consumers** (komodo / komodo-op may still need
     it — `grep` first); if Terraform was its only user, fold its
     removal in, else leave it and just drop the `tf`-runner mention.
   - `docs/hosts.html#bilby-cli-tools` — add a Terraform row next to
     `mcli` (chezmoi-managed install; config-as-code per component 1,
     not a manual doc step). Note it is **not bilby-special** — every
     chezmoi-managed machine gets it (Fedora branch on bilby, macOS
     branch on a Mac); the row is just discoverability.
   - `docs/plans/alligator-bilby-migration/terraform-setup.md` — **do
     not rewrite history**; add a one-line "superseded by
     tf-runner-decommission" note.
   - Colloquial `tf plan`/`tf apply` mentions in other plan docs
     (`clickstack-migration/*`, `pinelake-migration/*`,
     `railway-migrations.md`): leave as-is; reads as "terraform"
     generically.
6. **Codify the hard requirement.** Add to `AGENTS.md` "Hard rules":
   *podhaus Terraform must run from any machine — clone + chezmoi
   creds ⇒ `terraform` works; no host-pinned backend endpoint, no
   LAN-only provider `api_url`, no dockernet assumption in any TF
   root.* Mirror it in `docs/terraform.html` (the "how to run" +
   prerequisites sections). This is the durable guard so a future
   change can't silently re-pin TF to one host.
7. **Provider lockfile — don't commit it (decided).** The
   cross-platform lock-hash problem is dissolved by *removing* the
   shared file, not by adding tooling. In each TF root, add to
   `.gitignore`:
   ```
   .terraform.lock.hcl
   .terraform/
   ```
   and `git rm --cached cloudflare/.terraform.lock.hcl` (it's
   currently tracked). Each machine's `terraform init` then resolves
   providers within the `~> 5.0` / `~> 6.0` / `~> 0.41` constraints and
   writes its own local lock — no shared file, so no cross-platform
   mismatch, **ever**, and **zero ongoing maintenance / no automation /
   no new service**.
   - Accepted tradeoff (explicit operator decision): no exact-version
     pin or supply-chain hash pin. Different machines/times can land on
     different provider *patch* versions within the `~>` constraints; a
     bad upstream patch isn't fenced. Acceptable for homelab scale;
     constraints still bound it. If determinism for a specific provider
     is ever wanted, tighten its `version =` in `required_providers`
     (deliberate HCL edit) — no lockfile needed.
   - **Residual, and it is NOT a lockfile problem:** provider *build
     availability per platform* is independent of the lock. Even with
     no committed lock, `terraform init` on a Mac must still *download*
     a `darwin_arm64` build of **`ubiquiti-community/unifi`** (community
     fork) from the registry. If that platform build doesn't exist,
     the `cloudflare/` root is un-`init`-able on a Mac regardless of
     the lockfile. So the **UniFi-split decision is still conditionally
     open** — gating input is "does the fork publish a build for the
     operator's platform," verified from the registry, *not* anything
     about hashes. Reconcile the §"From-anywhere review" bullet with
     this framing.

### Out of scope

- Building the **rest** of the MinIO/Publii plan
  (`/home/nathan/.claude/plans/okay-make-a-plan-quiet-sprout.md`):
  the `minio/terraform/` buckets/service-account root, Publii prep, etc.
  Resumes after this on the from-anywhere foundation.
- **In scope by necessity (was previously deferred):** the MinIO S3
  Cloudflare exposure (`storage.pod.haus` ingress + WAF) — Ordering
  step 1 — is now an *upstream prerequisite* of this plan, applied
  with the current `tf` runner before it is deleted. It is no longer
  a "later, separate" item; the from-anywhere requirement pulls it
  forward.

## Verification

Tooling/plumbing change → **the acceptance test is zero drift**:

0. Pre-check: `grep -rn 'terraform\.workspace' cloudflare/*.tf` is
   empty (confirms the work `terraform.fish` won't block podhaus and
   no workspace assumption sneaks in).
0. Pre-check: `grep -rn 'terraform\.workspace' cloudflare/*.tf` empty;
   Ordering step 1 done (`storage.pod.haus` resolves, S3 reachable).
1. `chezmoi apply` installs Terraform (official HashiCorp repo, the
   right branch per OS) and renders `~/.config/fish/conf.d/podhaus-tf.fish`
   (0600); `terraform version` = expected official build ≥ the old
   image's.
2. Fresh fish shell (conf.d auto-sourced): `env | grep -E
   'CLOUDFLARE_API_TOKEN|AWS_ACCESS_KEY_ID'` shows values — no wrapper.
3. `cd cloudflare && terraform init -reconfigure` succeeds against
   `https://storage.pod.haus`; existing state found; **no migrate
   prompt** (decline + investigate if one appears — endpoint-only).
4. `terraform plan` → **zero resource changes** (incl. the
   `unifi_dns_record` resources — proves the `unifi.pod.haus` provider
   repoint reaches the controller). Any drift → stop, investigate.
5. No-op `terraform apply` (user-authorized per the unchanged AGENTS.md
   hard rule) completes cleanly.
6. **The acceptance test — from a non-bilby machine:** clone podhaus,
   `chezmoi apply` there, `cd cloudflare && terraform plan` → zero
   drift, no LAN/dockernet/loopback dependency hit. This is the hard
   requirement, proven.
7. `tf` deleted; `grep -rn '\.\./tf\b'` in podhaus shows only
   historical plan-doc mentions; `docs/terraform.html` reproducible
   with `terraform` directly; the new hard rule is in `AGENTS.md`.

## Risks / gotchas

- **Ordering dependency**: Ordering step 1 (`storage.pod.haus`
  exposure via the *current* runner) MUST land before this plan's
  backend repoint, or `terraform init` has no reachable backend. This
  is the single most important sequencing risk.
- **Lockfile** — not a risk: it's gitignored (component 7), so no
  cross-platform hash failure exists. The *remaining* per-platform
  risk is provider **build availability** (`ubiquiti-community/unifi`
  on a Mac) — tracked in §"From-anywhere review", lockfile-independent.
- **Two repos, two commits**: chezmoi changes land in
  `~/.local/share/chezmoi` (its own push + `chezmoi apply` per
  machine), podhaus changes in podhaus. Sequence: chezmoi first
  (Terraform + rendered conf.d env file must exist before podhaus-side
  verification), podhaus second.
- **`terraform init` backend change** needs `-reconfigure`; never
  accept a state *migration* prompt (endpoint-only change).
- **No more host pinning**: backend is the public endpoint, providers
  are public — Terraform now runs anywhere with chezmoi creds, per the
  hard requirement. Any future change reintroducing a LAN IP / dockernet
  name / loopback in a TF root violates the `AGENTS.md` hard rule and
  must be rejected in review.
- **UniFi over the tunnel**: `unifi.pod.haus` must stay published
  (`module "unifi"`) for the provider to work off-LAN. It already is
  (no posture change — the controller is tunnel-public today), but
  destroying that module would now also break Terraform itself.
  Note the coupling.
- **Don't touch** `~/.aws/config` or the `terraform`/`tf-dev`/
  `tf-prod` fish functions — work AWS, unrelated, breaking them breaks
  the user's day job.
- Authorization hard rule (`apply` / `git push` need a green light)
  **carries over verbatim**; this plan changes the command spelling,
  never the gate.
