# Terraform foundation — one root, 1Password provider, codified MinIO/state bootstrap

**Status: PLANNED.** Nothing applied/pushed. Every `apply` + the state
migration are gated; `terraform plan` is the safety instrument, not a
side effect. The relay work that originally listed this as prerequisite
shipped in its own `terraform/` root instead (the relay infra now lives
there independently); this consolidation remains the right cleanup but
no longer blocks anything.

## Why

Three findings (evidence, not assertion):

1. **The `cloudflare/` vs `minio/terraform/` split is incidental, not
   a DR firewall.** `minio/terraform/` manages only tenant resources
   (the `nathanbaxter-com` bucket/policy/IAM/service-account). It does
   **not** manage the `terraform-state` bucket or the MinIO daemon.
   The earlier "keep the state-store manager separate — principled"
   rationale does not hold.
2. **The DR story is uncodified.** The `terraform-state` bucket is
   created by a hand-run `mcli mb --with-versioning
   local/terraform-state` documented only in a *migration runbook*
   (`alligator-bilby-migration/terraform-setup.md`). `komodo-start`
   never touches MinIO; `disaster-recovery.html` only *checks* the
   bucket exists. Cold-start depends on tribal knowledge.
3. **Provider creds were dumped to disk.** Every provider credential
   (Cloudflare/UniFi/GitHub/MinIO-root) lives raw in the
   chezmoi-rendered `podhaus-tf.fish`. There is **zero** existing
   1Password Terraform-provider usage. Only the 1Password
   service-account token should ever be raw at rest.

The correct architecture (your model): **a bootstrap guarantees
MinIO + the state bucket; then one `terraform apply` — needing only
the 1Password service-account token — aligns the whole universe.**

## Target end-state

```
komodo-start  (idempotent bootstrap)
  └─ Komodo Core ─ ./komodo-sync ─ MinIO stack up
       └─ ENSURE terraform-state bucket (versioned)   ← new, codified
                         │
   one secret at rest:  OP_SERVICE_ACCOUNT_TOKEN
                         ▼
  terraform/  (ONE root)  ── terraform apply ──▶ aligns:
     Cloudflare · UniFi · GitHub · DigitalOcean(relay) · MinIO tenants
     all provider creds resolved at plan/apply via the onepassword
     provider (data "onepassword_item"); nothing else on disk.
```

## Components

### 1. Single consolidated root: `terraform/`

- New top-level `terraform/` (neutral, accurate, no vendor/abbrev —
  replaces `cloudflare/` *and* `minio/terraform/`). Recommended name;
  it touches `AGENTS.md` hard rules, `cloudflare/README.md`, the
  chezmoi env, and muscle memory — those references are enumerated in
  the completion checklist. Open to override.
- All existing `.tf` from both roots move in; providers reconciled in
  one `providers.tf`: `cloudflare`, `ubiquiti-community/unifi`,
  `integrations/github`, `aminueza/minio`, `1Password/onepassword`,
  and later `digitalocean/digitalocean` (added by the relay plan).
- Backend: the same S3-on-`storage.pod.haus` block, single
  `key = "podhaus.tfstate"`. From-anywhere hard rule unchanged
  (backend stays `https://storage.pod.haus`; no LAN/loopback).
- **State migration is the one high-risk step — treated as state
  surgery, gated, and proven by a zero-diff plan:**
  1. Snapshot: both existing state objects are already versioned in
     the bucket + Backrest; additionally `terraform state pull` each
     old root to a local file as a belt-and-braces copy.
  2. Stand up `terraform/` with all `.tf` + the unified backend key.
  3. Migrate every existing resource into the new state via
     `terraform import` (no destroy/recreate) — or `terraform state
     mv` against pulled local state files then `state push`; the
     exact mechanism is chosen against the *actual* state contents at
     execution (an Open item, not guessed here).
  4. **Gate: `terraform plan` MUST show zero changes.** A clean
     no-op plan is the proof the refactor is pure. Nothing proceeds
     until that is green. Old roots/state retained until then;
     rollback = keep using the old roots.

### 2. 1Password provider — one secret at rest

- `provider "onepassword"` (source `1Password/onepassword`; exact
  version + the `service_account_token` arg vs `OP_SERVICE_ACCOUNT_
  TOKEN` env confirmed from the provider docs at scaffold — index
  page is JS-gated to WebFetch; the `onepassword_item` data-source
  schema *is* confirmed: `vault` (UUID), `title`/`uuid`; fields via
  `.password`/`.username`/`.credential` or
  `.section_map["…"].field_map["…"].value`).
- The provider authenticates with the **1Password service-account
  token only**, supplied exactly as `komodo-start` already does it:
  the repo-root `OP_SERVICE_ACCOUNT_TOKEN` file / env. **No new
  mechanism.** This is the *single* secret at rest.
- Every other provider credential becomes a `data "onepassword_item"`
  (Homelab vault) referenced from the provider block:
  - Cloudflare API token, UniFi API key, GitHub token, MinIO
    root user/password, DigitalOcean PAT — each an item lookup.
  - The item/field layout is the contract (same principle as the
    komodo-op convention), e.g.
    `data.onepassword_item.cloudflare.credential`.
- **Delete** the chezmoi `podhaus-tf.fish` secret exports entirely
  (8 → 0). The from-anywhere contract becomes *stronger and simpler*:
  **clone podhaus + have the 1P service-account token ⇒ `terraform`
  works anywhere**, one secret, nothing else rendered to disk.
- Provider-blocks-referencing-data-sources is valid: the onepassword
  provider needs only the env token (no resource dependency), so its
  data sources resolve before the dependent providers configure.

### 3. Codified MinIO + state-bucket bootstrap (extend `komodo-start`)

`komodo-start` is a 93-line idempotent bootstrap that ends with
`./komodo-sync` (which deploys the `minio` stack). Append, **after**
`./komodo-sync`, an idempotent block:

- Poll MinIO health: `until curl -sf
  http://localhost:9000/minio/health/live` (bilby binds MinIO API on
  `127.0.0.1:9000`; bilby has host `mcli`).
- Configure an mcli alias from root creds read the same way the
  script already reads 1Password (`op read "op://Homelab/MinIO
  Root/username"` / `.../credential`).
- `mcli mb --ignore-existing --with-versioning local/terraform-state`
  — idempotent; safe on every run.

This converts state-bucket creation from "hand-run mcli buried in a
migration doc" to a guaranteed, idempotent step in the canonical
bootstrap — the actual DR fix.

### 4. The resulting DR story (the payoff)

Cold start, fully codified:

1. (If real DR) restore `/var/lib/minio` from Backrest; else fresh.
2. `./komodo-start` — idempotent: Komodo Core → `komodo-sync` →
   MinIO stack up → **terraform-state bucket guaranteed (versioned)**.
3. `cd terraform && terraform apply` — needs only the 1P
   service-account token; the onepassword provider resolves all
   other creds; one apply aligns Cloudflare/UniFi/GitHub/DO-relay/
   MinIO-tenants.
4. First apply runs from bilby/LAN (state reachable via
   split-horizon); the relay (in this same root) then makes
   from-anywhere true for every subsequent apply.

Documented into `disaster-recovery.html` (cold-start order) on
completion — replacing the "check the bucket exists" hand-wave.

## Hard-rule compliance

- [ ] Backend stays `https://storage.pod.haus`; single root, no
      LAN/loopback/dockernet. From-anywhere holds (and simplifies to
      one secret).
- [ ] Only `OP_SERVICE_ACCOUNT_TOKEN` at rest; all else via the
      onepassword provider. chezmoi `podhaus-tf.fish` deleted.
- [ ] State migration proven by a **zero-diff `terraform plan`**
      before any real apply; old state retained until then.
- [ ] komodo-start addition is idempotent (`mb --ignore-existing`).
- [ ] Provider resource docs read before writing HCL (DO v2 +
      onepassword data-source captured; onepassword provider block
      + versions verified at scaffold).
- [ ] Net effect is subtractive where it counts: 2 roots → 1,
      8 on-disk secrets → 1, manual DR step → codified.

## Gated execution sequence

1. Scaffold `terraform/` (all existing `.tf` moved in, onepassword
   provider added, creds swapped to data sources). No apply.
2. State migration (§1.3) → **gate: zero-diff `terraform plan`**.
   Reviewed and approved before anything else. **(gated)**
3. Apply the onepassword-provider swap — also must be zero-diff
   (pure credential-source change, no resource change). **(gated)**
4. Extend `komodo-start`; run it (idempotent) to materialize the
   state bucket guarantee; verify `mcli ls local/terraform-state`.
5. Delete the chezmoi `podhaus-tf.fish` exports; confirm `terraform`
   still plans clean with only the 1P token.
6. Update docs (`AGENTS.md` hard rules + key files,
   `cloudflare/README.md`→moved, `disaster-recovery.html`,
   `terraform.html`); retire the old root directories.
7. **Fold in the relay root** — the relay infra currently lives in
   its own `terraform/` root with `relay.tfstate`; the reserved IP
   crosses into `cloudflare/` via a `terraform_remote_state` reference.
   Folding it into the consolidated root makes that cross-root literal
   seam an intra-root reference (cleaner; not load-bearing).

## Rollback

Until step 2's zero-diff plan is approved and applied, the old
`cloudflare/` + `minio/terraform/` roots and their separate state
files are untouched and authoritative — rollback is "keep using
them." State objects are versioned in the bucket + Backrest, so even
a botched migration is recoverable to a prior version.

## Open items (close before scaffolding)

- Exact `onepassword` provider version + auth arg syntax — confirm
  from `developer.1password.com/docs/terraform` (JS-gated to
  WebFetch; use an authenticated fetch / `gh` at scaffold).
- The precise state-migration mechanism (`terraform import` vs cross
  `state mv`) — decided against the actual pulled state contents, not
  guessed.
- `terraform/` root name confirmation (vs e.g. keeping `cloudflare/`
  as the dir — not recommended; it's no longer Cloudflare-only).

## Decided

One consolidated root; 1Password provider as the sole credential
mechanism (only the SA token at rest); MinIO + `terraform-state`
bootstrap codified by extending `komodo-start`; sequencing =
**foundation first, relay drops into the single root after**.
