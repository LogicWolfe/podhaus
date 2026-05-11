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

## State storage

Local file on bilby at `/var/lib/terraform-state/`, captured by the
existing Backrest nightly pipeline (same pattern as every other
bilby-local stack state). **No R2, no Terraform Cloud, no 1P-custom-
wrapper.** The backup+restic+rclone pipeline already proven in earlier
phases is the durability mechanism.

## Execution runtime

Terraform via Docker, same shape as DNSControl
(`dns-push` / `dns-preview` are 9-line bash wrappers around
`docker run ghcr.io/stackexchange/dnscontrol`). New wrappers:
`cf-plan` / `cf-apply` (or similar naming) around
`hashicorp/terraform:latest`.

## DNS migration

DNSControl → Terraform in the same pass. Single unified tool for all
Cloudflare. DNSControl keeps working during the transition so there's
no urgency.

## Steps (in order)

1. **Decide final naming for the Terraform setup directory** — likely
   `cloudflare/` at repo root (matches `dns/`, `cloudflare-tunnel/`).
   Contains `.tf` files, `terraform.tfstate` symlink or equivalent
   pointing at `/var/lib/terraform-state/cloudflare.tfstate`, a
   `README.md`.
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
5. **Set up state file + Backrest plan**:
   - Create `/var/lib/terraform-state/` with correct ownership.
   - Add bind mount entry in `backup/compose.shared.yaml`:
     `/var/lib/terraform-state:/userdata/terraform-state:ro`.
   - Add plan in `backup/bilby/config.json.tmpl`: `terraform-state`
     plan, 04:00 AWST or co-schedule with an existing one,
     `14 daily + 4 weekly + 6 monthly` retention.
   - Komodo redeploy, trigger first snapshot manually, verify it
     lands on Jump + OneDrive.
6. **Write the runner wrappers** — `cf-plan` (equivalent to
   `dns-preview`) and `cf-apply` (equivalent to `dns-push`). Load the
   CF token from 1P via `op run`, mount state directory, invoke
   `hashicorp/terraform:latest`.
7. **Run `terraform plan`** against the imported HCL — verify zero
   drift from the current live account (this is the proof that the
   import worked).
8. **Add the new Access Application for the Komodo webhook bypass**
   (the immediate Railway-migrations driver). Scoped to exactly
   `komodo.pod.haus/<komodo-webhook-path>`, Bypass policy, HMAC
   validated on Komodo's end. `terraform plan && terraform apply`.
9. **Add a scoped Access Application for `paperless.pod.haus` with a
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
10. **Migrate DNS from DNSControl**:
    - Import current zones (already done in the cf-terraforming sweep
      above).
    - Resolve any differences between DNSControl's declarative shape
      and the HCL output.
    - Confirm `terraform plan` shows zero drift once the HCL matches
      reality.
    - Run for a week in parallel (both tools can "plan" against the
      account; neither can write simultaneously — apply only via
      Terraform after this point).
    - Retire `dns-preview` / `dns-push` scripts and the `dns/`
      directory once confident.
    - Delete the DNSControl-specific `.env` and `creds.json` files
      from 1P and repo.
11. **Restore drill for terraform state** — delete
    `/var/lib/terraform-state/cloudflare.tfstate` locally, restore
    from Backrest snapshot, confirm `terraform plan` still shows
    clean. Same cadence as the Plex restore drill.
12. **Decide fate of `LogicWolfe/cf-access-sync` repo** — archive on
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
