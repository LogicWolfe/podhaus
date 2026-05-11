# Cloudflare as Terraform

Replace DNSControl + the planned cf-access-sync tool with a single
Terraform surface covering Cloudflare Access, DNS, Rulesets, Transform
Rules, Single Redirects, Cache Rules, Zone Settings, and everything
else hand-configured in the dashboard today. **Blocks** the Railway
migrations work which needs a path-scoped Access Bypass Application
for the Komodo webhook.

## Decision context (recorded 2026-04-17)

While planning Phase 11, the webhook delivery from GitHub → Komodo
needed a path-scoped Cloudflare Access Bypass Application. Three paths
considered:

1. **Manage via dashboard** — violates the config-as-code principle.
2. **Write a small config-sync tool (cf-access-sync)** — got as far
   as spec + design docs in a new public repo
   (`LogicWolfe/cf-access-sync` on GitHub).
3. **Terraform** — handles every Cloudflare resource via one tool;
   the "Terraform is too heavy" objection mostly dissolves for solo
   homelab scale. One tool beats two. `cf-terraforming` imports
   existing state with one command.

Accepted #3. cf-access-sync is now historical thinking; decide its
disposition at the end of this work (probably archive on GitHub).

## Foundation prerequisite

State storage and the `tf` runner are spun up separately in
[Terraform foundation](terraform-setup.md) — a MinIO stack on
bilby plus a `./tf` wrapper that joins dockernet. That plan must
land first; the rest of this page assumes:

- A `terraform-state` bucket in MinIO with versioning enabled.
- A `MinIO Terraform User` 1P item for the S3 backend credentials.
- A `./tf` runner that injects `AWS_*` and `CLOUDFLARE_API_TOKEN`
  via `op run`.

The CF state is one object key inside that shared bucket
(`cloudflare.tfstate`). Future TF-managed tools land alongside as
sibling keys.

## Progress (2026-05-11)

| Item | Status |
|---|---|
| `cloudflare/` scaffold | ✓ `backend.tf`, `providers.tf`, `variables.tf`, `.env`, `.gitignore` |
| `cloudflare_dns_record` import flow | ✓ proven via import blocks + `tf plan -generate-config-out` |
| `pod.haus` DNS (26 records) | ✓ migrated, **zero drift**, cleaned up with `for_each` + `local.zones`/`local.tunnels` |
| 10 remaining zones DNS | pending — see "Known quirks" below for SRV+URI |
| 10 Access Apps + policies | pending |
| Rulesets / Cache Rules / Transform Rules | pending |
| Zone settings | pending |
| Komodo webhook Bypass Access App | pending |
| Paperless iOS service-token Access App | pending |
| Retire DNSControl `dns/` directory | pending |

## Known quirks (provider v5)

Discovered during the pod.haus migration:

- **SRV and URI records** use the `data { … }` attribute, not `content`.
  `tf plan -generate-config-out` emits both and the generated HCL fails
  validation with "Attribute 'data' cannot be specified when 'content'
  is specified". Hand-write these from the CF API's `data` payload:
  see `cloudflare/README.md` for the SRV resource shape. Affects:
  - `nathanbaxter.com` SRV records (caldav, carddav, imap, pop3, submission)
  - `nathanbaxter.net` and `nathanbaxter.org` URI redirects
- **`comment` field** sometimes appears in CF on records that
  DNSControl never set (e.g. Postmark DKIM). Preserve it in HCL rather
  than dropping it, or `tf plan` shows a one-line drift.

## DNS migration

DNSControl → Terraform in the same pass. Single unified tool for all
Cloudflare. DNSControl keeps working during the transition so there's
no urgency.

## Steps (in order)

Assumes [Terraform foundation](terraform-setup.md) has landed.

1. **Lay out `cloudflare/` at the repo root** (sibling to `dns/`,
   `cloudflare-tunnel/`). Contains `.tf` files plus a `backend.tf`
   pointing at `key = "cloudflare.tfstate"` in the shared MinIO
   `terraform-state` bucket. No state file in the repo — that lives
   in MinIO.
2. **Scope the Cloudflare API token** — check whether the existing
   `op://Homelab/Cloudflare API Token/credential` has all the
   Terraform-required scopes (Zone DNS Read/Write, Access Apps/Policies
   Read/Write, Rulesets Read/Write, Cache Rules Read/Write, Zone
   Settings Read/Write, Workers Read/Write). Recorded as having ~20
   scopes including all CF Access + Tunnel work — double-check DNS
   Edit is on there before switching.
3. **Run `cf-terraforming`** against the account to generate HCL for
   existing state:
   - Access Applications (10 apps: Pod Haus wildcard, UniFi, Home
     Assistant, Syncthing, Sunshine, Torrents, Pine Lake
     SSH/Torrent/Syncthing, App Launcher)
   - Access Policies (attached to each Application)
   - Zone DNS records (`pod.haus`, `pinelake.haus`, currently in
     DNSControl)
   - Transform Rules, Single Redirects, Cache Rules that were
     hand-configured
   - Zone-level settings (SSL mode, etc.)
4. **Clean up the generated HCL** — cf-terraforming output is correct
   but often clunky. Organize by resource type into separate `.tf`
   files.
5. **`op run -- ./tf init`** against the imported HCL — first init
   creates the `cloudflare.tfstate` object in the MinIO bucket.
6. **`op run -- ./tf plan`** — verify zero drift from the current
   live account (this is the proof that the import worked).
7. **Add the new Access Application for the Komodo webhook bypass**
   (the immediate Railway-migrations driver). Scoped to exactly
   `komodo.pod.haus/<komodo-webhook-path>`, Bypass policy, HMAC
   validated on Komodo's end. `./tf plan && ./tf apply`.
8. **Add a scoped Access Application for `paperless.pod.haus` with a
   service-token bypass** so the Swift Paperless iOS app can
   authenticate with `CF-Access-Client-Id` / `CF-Access-Client-Secret`
   headers instead of interactive login. Why scoped-not-wildcard: a
   bypass policy on the existing `*.pod.haus` app would unlock every
   subdomain if the token leaked off the phone; a dedicated
   `paperless.pod.haus` app is more specific than the wildcard and
   takes precedence. Shape: new `access_service_token` resource named
   `Paperless iOS` (save Client ID + Secret to
   `op://Homelab/Paperless iOS Access Token`), new
   `access_application` for `paperless.pod.haus`, two policies —
   Bypass (precedence 1) matching the service token, Allow (precedence
   2) matching the same "Family allow" group as the wildcard so
   browser access still works. Then paste both headers into Swift
   Paperless → Settings → connection → Extra Headers.
9. **Migrate DNS from DNSControl**:
   - Import current zones (already done in the cf-terraforming sweep
     above).
   - Resolve any differences between DNSControl's declarative shape
     and the HCL output.
   - Confirm `./tf plan` shows zero drift once the HCL matches
     reality.
   - Run for a week in parallel (both tools can "plan" against the
     account; neither can write simultaneously — apply only via
     Terraform after this point).
   - Retire `dns-preview` / `dns-push` scripts and the `dns/`
     directory once confident.
   - Delete the DNSControl-specific `.env` and `creds.json` files
     from 1P and repo.
10. **Decide fate of `LogicWolfe/cf-access-sync` repo** — archive on
    GitHub (read-only, with README note pointing to the Terraform
    approach as the actual path), delete outright, or keep as
    "documented thinking" for anyone who wants a reference.
    Recommend archive.

## Deferred / future

- **Migrating Cloudflare Tunnel config** from
  `cloudflare-tunnel/conf/config.yml` to Terraform. Tunnels can be
  managed via TF but the current file-based config works and
  cloudflared reads it natively; low-priority unless we want the full
  Cloudflare surface in one state file.
- **Terraform-managed Identity Providers** (GitHub OAuth, Google, etc.
  currently configured in the dashboard). These are long-lived,
  set-and-forget — low value to codify.
