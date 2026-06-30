# Pocket ID — passkey OIDC provider for Cloudflare Access

Stand up a self-hosted [Pocket ID](https://pocket-id.org) instance at
`id.pod.haus` as a passkey-first OIDC identity provider, and wire it into
Cloudflare Zero Trust Access **as an additional login method alongside the
existing GitHub login**. Cloudflare Access stays the authority on *who* is
allowed (the existing `Family` group is unchanged); Pocket ID only adds a
new way to *authenticate* — WebAuthn passkeys. The concrete near-term win
is a clean first-ever login for Sky, plus an identity layer we own.

This plan is built on verified facts (Pocket ID **v2.9.0**, Cloudflare
provider **~> 5.0**), not the generic template it grew from. Every value
below has been checked against source/docs; the load-bearing ones are
called out in **Derisking** so they don't get lost.

---

## Decisions (settled)

- **Domain:** `id.pod.haus` (pod.haus zone). Team domain is
  `podhaus.cloudflareaccess.com`, so the OIDC callback is
  `https://podhaus.cloudflareaccess.com/cdn-cgi/access/callback`.
- **Identities:** `nathan@nathanbaxter.com` and `scroeser@gmail.com` — the
  identities already in the `Family` group (`terraform/access.tf:21`). No
  new email addresses, no new Access group. Pocket ID issues an `email`
  claim carrying these; the existing Family rules match it.
- **Authority model:** Pocket ID is **added** as an IdP. GitHub login stays
  configured. No `auto_redirect_to_identity`, so the Access chooser lists
  both and you pick "Pocket ID." This keeps GitHub as a working fallback
  and removes essentially all lockout risk.
- **Authorization is unchanged.** `Family` group as-is. Going passkey-only
  fleet-wide (single IdP + auto-redirect) is a **separate, later, gated**
  decision — see [Deferred](#deferred-explicitly-out-of-scope).
- **Host:** bilby. Single-service `files_on_host` stack, SQLite on a local
  named volume (never NFS — storage tier rule).

---

## Derisking — the things that would actually break this

Every item here is a verified failure mode with a verified fix. Read before
implementing.

1. **Cloudflare verifies the OIDC token server-side, so the IdP's OIDC
   endpoints must be publicly reachable and NOT behind Access.** During
   login, Cloudflare's own servers (egress ASN **13335**) do the
   authorization-code exchange against `token_url` and validate the
   `id_token` signature against `certs_url` (JWKS). The dreaded
   `Failed to verify oidc token with fresh keys` error *is* that fetch
   failing. This is documented for exactly our scenario (self-hosted IdP
   behind a Cloudflare tunnel) in
   [pocket-id discussion #891](https://github.com/pocket-id/pocket-id/discussions/891).
   **Fixes, all applied below:**
   - `id.pod.haus` gets a **dedicated Access app with a bypass-everyone
     policy** (more-specific app overrides the `*.pod.haus` wildcard's
     Family gate — same primitive as `module.sky`/`module.unifi`). Pocket
     ID's own passkey login protects the admin UI, so a public edge is
     correct here, not a leak.
   - **PKCE (S256) enabled** on both the Pocket ID client and the
     Cloudflare IdP.
   - **Bot Fight Mode off** for pod.haus, and a **WAF skip rule** so
     Cloudflare's ASN-13335 fetches aren't challenged (prepared HCL in
     [Terraform](#3-terraform-cloudflare-side); apply only if the IdP
     Test fails — pod.haus may not have Bot Fight Mode on at all).

2. **`APP_URL` *is* the WebAuthn RP ID.** Pocket ID derives the relying-party
   ID and origin from `APP_URL` (`hostname(APP_URL)` →
   `webauthn_service.go`). It must be exactly `https://id.pod.haus` (scheme
   + host, no path, no trailing slash). A mismatch silently breaks passkey
   registration and login. **Corollary:** changing the hostname later
   invalidates every enrolled passkey. Pick `id.pod.haus` and keep it.

3. **Users must have an email or Cloudflare can't match them.** Pocket ID
   users are emailless by default; the `email` claim only appears if the
   user record has an email. Both users are created **with** their email
   (above), and we leave `REQUIRE_USER_EMAIL` at its default `true` so the
   API rejects an emailless user rather than producing a token that gets
   denied at the edge.

4. **`ENCRYPTION_KEY` is mandatory and a restore needs the same key.** It
   encrypts secrets and signing keys at rest. It lives in 1Password
   (Homelab vault) — never in git, never in the restic repo. A backup
   restored with a different key leaves those columns unreadable. (Pocket
   ID's docs are silent on this; it's a source-level certainty — flagged so
   nobody learns it the hard way.)

5. **arm64 is fine.** `ghcr.io/pocket-id/pocket-id:v2.9.0` and `:v2` are
   multi-arch (linux/amd64 + linux/arm64, verified from the GHCR manifest),
   so bilby's M1 pulls the native image. No build-from-binary needed (this
   was the one finding that could have changed the whole approach).

6. **Terraform `client_secret` shows perpetual drift.** The Cloudflare API
   returns the OIDC client secret as `CONCEALED_STRING`, so every plan
   wants to "update" it
   ([provider issue #4497](https://github.com/cloudflare/terraform-provider-cloudflare/issues/4497)).
   Mitigated with `lifecycle { ignore_changes = [config.client_secret] }`.

7. **Lockout avoidance / sequencing.** Bring Pocket ID up and enrol your
   admin passkey *before* any Terraform touches Access. Because we don't
   set `allowed_idps`/auto-redirect, GitHub login keeps working throughout
   — even if Pocket ID is misconfigured you can still reach
   `komodo.pod.haus` to fix it.

---

## What gets built

### 1. `pocket-id/` stack (bilby)

`pocket-id/compose.yaml`:

```yaml
services:
  pocket-id:
    container_name: pocket-id
    # Multi-arch (arm64 ✓). Pin by digest at implementation time:
    #   docker buildx imagetools inspect ghcr.io/pocket-id/pocket-id:v2.9.0
    # then append @sha256:… as every other pinned stack does (see bugsink).
    image: ghcr.io/pocket-id/pocket-id:v2.9.0
    restart: unless-stopped
    mem_limit: 256m            # Go binary + SQLite; idle is tens of MB
    environment:
      # APP_URL == WebAuthn RP ID == OIDC issuer. Exact public origin.
      APP_URL: https://id.pod.haus
      ENCRYPTION_KEY: ${POCKET_ID_ENCRYPTION_KEY}
      # Behind cloudflared (TLS terminates at the CF edge). TRUSTED_PLATFORM
      # gives correct client IPs in the audit log from CF-Connecting-IP.
      TRUST_PROXY: "true"
      TRUSTED_PLATFORM: cf-connecting-ip
      # Own the /app/data volume as 1000:1000.
      PUID: "1000"
      PGID: "1000"
      # Structured logs for the Alloy → ClickStack pipeline; no outbound
      # calls from a homelab IdP.
      LOG_JSON: "true"
      ANALYTICS_DISABLED: "true"
      VERSION_CHECK_DISABLED: "true"
      TZ: ${TZ}
      # DB defaults to SQLite at data/pocket-id.db — DB_PROVIDER was removed
      # in v2 (type auto-detected from the connection string). Don't set it.
    volumes:
      - pocket-id-data:/app/data   # SQLite db + uploads; local disk only
    networks:
      - dockernet
    labels:
      autoheal: "true"
      podhaus.stack-content-hash: ${STACK_CONTENT_HASH:-unset}
    healthcheck:
      # The image's built-in CLI healthcheck (hits localhost:1411). Works
      # on both the alpine and distroless variants — no shell dependency.
      test: ["CMD", "/app/pocket-id", "healthcheck"]
      interval: 90s
      timeout: 5s
      start_period: 10s
      retries: 3

networks:
  dockernet:
    external: true

volumes:
  pocket-id-data:
```

`pocket-id/stack.toml`:

```toml
[[stack]]
name = "pocket-id"
description = "Pocket ID — passkey-first OIDC identity provider for Cloudflare Access"
tags = ["podhaus"]

[stack.config]
server = "podhaus"
files_on_host = true
run_directory = "/etc/komodo/repo/pocket-id"
# No init container → no ignore_services. No deploy flag (lint forbids it).

environment = """
TZ=[[TZ]]
POCKET_ID_ENCRYPTION_KEY=[[OP__KOMODO__POCKET_ID_ENCRYPTION_KEY__CREDENTIAL]]
"""
```

Notes:
- Port `1411` is the app's internal listen port; the tunnel reaches it by
  container name (`http://pocket-id:1411`). No host port published.
- `UI_CONFIG_DISABLED` is deliberately **omitted** during rollout so the
  admin UI (OIDC clients, users, API keys) isn't constrained while
  bootstrapping. It can be added later as hardening if desired — it locks
  the *general settings* screen to env, not user/client management.

### 2. 1Password (Homelab vault)

Three items, each consumed by the mechanism that fits its consumer — no
secret ever lands in git or a shell env. Create:

| 1P item | Structure | Consumed as | By |
|---|---|---|---|
| `Pocket ID Encryption Key` | API Credential, `credential` field (= `openssl rand -base64 32`) | `OP__KOMODO__POCKET_ID_ENCRYPTION_KEY__CREDENTIAL` Komodo Variable | the container, via `stack.toml` |
| `Pocket ID OIDC` | section `OIDC` with `client id` + `client secret` (CONCEALED) fields | `data "onepassword_item"` at plan time | Terraform, directly |
| `Pocket ID API Key` | API Credential, `credential` field | read ad-hoc for provisioning curl | the operator running Phase E |

- The **encryption key** is a *container* secret, so it rides the normal
  container path: komodo-op slugifies `<Item Name>__<field label>` to
  `OP__KOMODO__POCKET_ID_ENCRYPTION_KEY__CREDENTIAL`; create the item, wait
  ~1 min for the sync (or `docker restart onepassword`), reference it as the
  `[[OP__KOMODO__…]]` variable in `stack.toml`.
- The **OIDC client id/secret** are a *Terraform* secret, so they're read
  **directly by Terraform via the already-declared `1Password/onepassword`
  provider** (`data "onepassword_item"`, §3) — no `TF_VAR`, no chezmoi edit,
  no shell env. This is the first data-source consumer of that provider,
  which `backend.tf` keeps declared for exactly this ("items with …
  'client id'/'client secret'"). The `TF_VAR` + chezmoi route the legacy
  creds use only exists because those pre-existing items have root-level
  fields with random-UUID field IDs the data source can't map; a fresh item
  we structure with a named section avoids that entirely.
- The **API key** is created in the Pocket ID admin UI after bootstrap
  (can't be bootstrapped via API). Store it in 1P so Phase E (and any later
  user management) can read it ad-hoc; it's not consumed by Terraform or the
  container.

> komodo-op will also sync `Pocket ID OIDC` into unused `OP__KOMODO__…`
> Komodo Variables (it syncs every Homelab item). Harmless — nothing
> references them; the container never sees the OIDC client creds.

### 3. Terraform (Cloudflare side)

All in the one consolidated `terraform/` root.

**`terraform/backend.tf`** — bump the onepassword provider pin so the
`section_map`/`field_map` accessors exist (added in v3.1.0; `~> 3.0` permits
3.0.x where they don't):

```hcl
    onepassword = {
      source  = "1Password/onepassword"
      version = "~> 3.1"   # was ~> 3.0; need section_map (v3.1.0+) to read the OIDC item
    }
```

**`terraform/access.tf`** — read the OIDC client creds straight from
1Password, then the IdP (the only genuinely new resource type). No
`variable`, no `TF_VAR`:

```hcl
# First data-source consumer of the declared onepassword provider. The
# "Pocket ID OIDC" Homelab item has an "OIDC" section with CONCEALED
# "client id" / "client secret" fields. section_map/field_map keys are the
# exact (case-sensitive) labels.
data "onepassword_vault" "homelab" {
  name = "Homelab"
}

data "onepassword_item" "pocket_id_oidc" {
  vault = data.onepassword_vault.homelab.uuid   # data source takes the vault UUID, not the name
  title = "Pocket ID OIDC"
}

# Pocket ID as a generic OIDC identity provider. ADDED alongside the
# dashboard-managed GitHub IdP — allowed_idps is intentionally NOT set on
# any app, so both remain selectable (Access shows a chooser). Going
# passkey-only later means setting allowed_idps=[this] + auto_redirect on
# the target app(s); that's a separate gated change.
resource "cloudflare_zero_trust_access_identity_provider" "pocket_id" {
  account_id = var.account_id
  name       = "Pocket ID"
  type       = "oidc"

  config = {
    client_id     = data.onepassword_item.pocket_id_oidc.section_map["OIDC"].field_map["client id"].value
    client_secret = data.onepassword_item.pocket_id_oidc.section_map["OIDC"].field_map["client secret"].value
    auth_url      = "https://id.pod.haus/authorize"
    token_url     = "https://id.pod.haus/api/oidc/token"
    certs_url     = "https://id.pod.haus/.well-known/jwks.json"
    scopes        = ["openid", "email", "profile"]
    pkce_enabled  = true
  }

  # Provider returns the secret as CONCEALED_STRING → perpetual drift.
  lifecycle {
    ignore_changes = [config.client_secret]
  }
}
```

> Field values from the data source are marked sensitive automatically, and
> a missing item/label is a hard plan-time error (fail-fast), not an empty
> string. The item must exist before `terraform plan` — it's populated in
> Phase C, before the Phase D apply.

**`terraform/services_pod_haus.tf`** — the service module. Note the
**public-bypass** policy (this is the load-bearing override; the default
Family chain would gate the IdP and break the JWKS fetch):

```hcl
# id.pod.haus — the Pocket ID IdP itself. MUST be publicly reachable so
# Cloudflare's servers can fetch the OIDC token/JWKS endpoints; a
# bypass-everyone policy overrides the *.pod.haus Family gate (same
# mechanism as module.sky/module.unifi). Pocket ID's own passkey login
# protects the admin UI.
module "pocket_id" {
  source = "./modules/pod_haus_service"

  account_id    = local.pod_haus_service_defaults.account_id
  zone_id       = local.pod_haus_service_defaults.zone_id
  tunnel_target = local.pod_haus_service_defaults.tunnel_target

  hostname = "id"
  backend  = "http://pocket-id:1411"

  access_policy_ids = [
    cloudflare_zero_trust_access_policy.public_bypass.id,
  ]
}
```

**`terraform/tunnel.tf`** — add one line to `pod_haus_module_ingress`:

```hcl
    module.pocket_id.ingress_rule,
```

**Prepared mitigation (apply only if the IdP Test fails with "fresh
keys").** Bot Fight Mode lives at the zone level — first verify whether
it's even on for pod.haus (Dashboard → pod.haus → Security → Bots). If the
Test still fails after it's off, add a WAF skip so Cloudflare's own egress
isn't challenged:

```hcl
# Let Cloudflare's server-side OIDC fetches (ASN 13335) reach the IdP
# unchallenged. Only needed if the Zero Trust IdP "Test" fails with
# "Failed to verify oidc token with fresh keys". Mirror the v5 ruleset
# shape already used in umami_analytics.tf.
resource "cloudflare_ruleset" "id_pod_haus_waf_skip" {
  zone_id = local.zones["pod.haus"]
  name    = "id.pod.haus — skip security for Cloudflare OIDC fetches"
  kind    = "zone"
  phase   = "http_request_firewall_custom"

  rules = [{
    ref         = "id_pod_haus_cf_egress_skip"
    description = "Skip managed WAF + security products for AS13335 hitting the IdP"
    expression  = "(http.host eq \"id.pod.haus\" and ip.geoip.asnum eq 13335)"
    action      = "skip"
    enabled     = true
    action_parameters = {
      phases   = ["http_request_firewall_managed"]
      products = ["waf", "bic", "rateLimit", "securityLevel"]
    }
  }]
}
```

> Confirm the exact `action_parameters`/expression fields against the
> v5 `cloudflare_ruleset` docs before apply (per the repo hard rule on
> reading provider docs) — schemas drift across minors.

### 4. Monitoring (Gatus)

Add to `gatus/conf/config.yaml`, slotting beside the other internal HTTP
services and inheriting the shared `*defaults` (which carries the
`alerts: *alerts` → Fenwick route and the `[STATUS]` conditions):

```yaml
  - name: Pocket ID
    url: http://pocket-id:1411/healthz
    <<: *defaults
    group: Identity
```

(`/healthz` returns 200 when healthy. Probe the **internal** dockernet name,
never the public host — an Access-gated public probe would 302 to the login
page and false-green, per the 2026-05-30 postmortem. id.pod.haus is
bypass-everyone so a public probe would actually work, but the internal
probe is the convention and avoids the edge entirely.)

### 5. Backup

Pocket ID's state is the SQLite db + uploads under `/app/data`. Fold it into
the existing backrest plan on bilby (the storage-tier-correct repo on Jump,
with the nightly rclone→OneDrive off-site sync riding the `backrest-state`
plan's success hook). Two coordinated edits:

- **`backup/bilby/compose.yaml`** — mount the named volume read-only as a
  backup source (same pattern as the other named-volume stacks), and
  declare it external:
  ```yaml
      - pocket-id-data:/userdata/pocket-id:ro
  # …and under top-level volumes::
  #   pocket-id-data:
  #     external: true
  ```
- **`backup/bilby/config.json.tmpl`** — add a plan (pick a free slot;
  `35 5 * * *` is open):
  ```json
  {
    "id": "pocket-id",
    "repo": "podhaus",
    "paths": ["/userdata/pocket-id"],
    "schedule": { "cron": "35 5 * * *", "clock": "CLOCK_LOCAL" },
    "retention": { "policyTimeBucketed": { "daily": 14, "weekly": 4, "monthly": 6 } },
    "hooks": [],
    "skipIfUnchanged": true
  }
  ```

This snapshots the SQLite db file directly — the same approach every other
SQLite stack uses (bugsink, gatus, mumble). A logical `pocket-id export`
zip via an ofelia job was considered as belt-and-suspenders but **deferred**:
it's non-standard for the fleet and `export`'s non-interactive
overwrite behaviour isn't verified (a nightly prompt could hang the job).
The volume snapshot is sufficient. **The `ENCRYPTION_KEY` is the other half
of every backup** — it stays in 1Password; a restore (`pocket-id import
--path … --yes` then restart) requires the same key.

---

## Order of operations

Dependency-ordered. **H** = needs a human with an authenticator/browser;
**A** = agent-automatable. Nothing pushes/applies without explicit
authorization (repo hard rule).

**Phase A — container up (A, then verify H)**
1. Create the `Pocket ID Encryption Key` 1P item; wait for komodo-op sync.
2. Write `pocket-id/compose.yaml` + `pocket-id/stack.toml` (pin the image
   digest). Commit, push (or `./komodo-sync` for local iteration).
3. Verify: `https://id.pod.haus` serves the Pocket ID page and
   `https://id.pod.haus/.well-known/openid-configuration` returns JSON with
   `issuer: https://id.pod.haus`. *(Needs the tunnel ingress — if doing
   Phase A before the Terraform in Phase D, temporarily confirm via the
   container/dockernet; the public hostname only resolves once §3's module
   + tunnel entry are applied. Simplest is to apply the `module.pocket_id`
   DNS+tunnel+app part of Phase D first, then this check passes publicly.)*

**Phase B — admin bootstrap (H, Nathan)**
4. Browse to `https://id.pod.haus/setup`, create the admin account, set the
   admin email to **`nathan@nathanbaxter.com`**, and enrol your admin
   passkey. Enrol a **second** credential immediately (second passkey or an
   offline hardware key) so a lost device can't lock you out of the IdP.
5. Settings → Admin → API Keys → generate one; store it in the
   `Pocket ID API Key` 1P item.

**Phase C — OIDC client (A or H)**
6. Create the client (UI: Settings → Admin → OIDC Clients, or API):
   ```bash
   curl -X POST https://id.pod.haus/api/oidc/clients \
     -H "X-API-KEY: $KEY" -H 'Content-Type: application/json' \
     -d '{"name":"Cloudflare Zero Trust",
          "callbackURLs":["https://podhaus.cloudflareaccess.com/cdn-cgi/access/callback"],
          "isPublic":false,
          "pkceEnabled":true}'
   # capture "id" from the response, then mint the secret:
   curl -X POST https://id.pod.haus/api/oidc/clients/<id>/secret -H "X-API-KEY: $KEY"
   ```
   Confidential client (`isPublic:false`) + PKCE. Put the client id +
   secret into the `Pocket ID OIDC` 1P item (section `OIDC`, CONCEALED
   fields `client id` / `client secret`) — that's the whole handoff to
   Terraform; the data source reads it at plan time.

**Phase D — Terraform the Cloudflare side (A; apply is H-authorized)**
7. Add the §3 pieces: the `backend.tf` provider pin bump, the `access.tf`
   data sources + IdP, the `module.pocket_id` block (public-bypass), the
   `tunnel.tf` ingress line. Run `terraform init -upgrade` first (the
   provider pin changed), then `plan`.
   `cd terraform && terraform plan`, review, then `apply` once authorized.
   This creates the `id.pod.haus` CNAME, the bypass Access app, the tunnel
   ingress, and the IdP.
8. Verify Bot Fight Mode state for pod.haus; hold the WAF-skip ruleset in
   reserve.

**Phase E — create the people (A)**
9. Create Sky (Nathan already exists from Phase B):
   ```bash
   curl -X POST https://id.pod.haus/api/users -H "X-API-KEY: $KEY" \
     -H 'Content-Type: application/json' \
     -d '{"username":"sky","email":"scroeser@gmail.com","firstName":"Sky","lastName":"Croeser"}'
   # then a one-time enrolment link (ttl is a duration string, max 31d):
   curl -X POST https://id.pod.haus/api/users/<id>/one-time-access-token \
     -H "X-API-KEY: $KEY" -H 'Content-Type: application/json' -d '{"ttl":"168h"}'
   # → {"token":"…"} → hand out https://id.pod.haus/lc/<token> out of band
   ```
10. Sky (H) opens her link, enrols a passkey; recommend a second credential.

**Phase F — verify end to end (H)**
11. Zero Trust → Integrations → Identity providers → **Test** next to
    Pocket ID. A green result (showing the returned claims, incl. `email`)
    proves the full round trip *including* the server-side JWKS fetch. If it
    fails with "fresh keys," apply the Bot-Fight-off / WAF-skip mitigation.
12. Incognito → a Family-gated app (e.g. `gatus.pod.haus`) → choose Pocket
    ID → passkey → land authorized. Repeat as Sky / with her identity.
13. Zero Trust → Users: both identities appear (two seats; free tier covers
    50). Gatus shows `Pocket ID` green.

**Phase G — backup (A; apply is H-authorized)**
14. Add the §5 volume mount + backrest plan. Push. Confirm the `pocket-id`
    plan runs and a snapshot lands in the repo.

---

## Failure modes & fixes

| Symptom | Cause | Fix |
|---|---|---|
| `Failed to verify oidc token with fresh keys` | CF can't fetch JWKS/token (gated, Bot Fight Mode, WAF) | Confirm `id.pod.haus` bypass app is live + most-specific; Bot Fight Mode off; apply ASN-13335 WAF skip; PKCE on both sides |
| Authenticated, then denied | Pocket ID user has no/!matching email | Set the user's email to the exact Family-matched address |
| Passkey enrol/login fails | `APP_URL` ≠ public origin (RP ID mismatch) | `APP_URL=https://id.pod.haus`, exact, no trailing slash; recreate passkeys if it was wrong |
| `terraform plan` always wants to change the client secret | API returns `CONCEALED_STRING` | `ignore_changes = [config.client_secret]` (already in §3) |
| Stack marked Unhealthy | (n/a — no init container here) | — |
| Locked out of everything | only if you later set single-IdP auto-redirect before a passkey exists | not in this plan; GitHub login stays as fallback |

---

## Deferred (explicitly out of scope)

- **Passkey-only / auto-redirect fleet-wide.** Setting
  `allowed_idps=[pocket_id]` + `auto_redirect_to_identity=true` (requires
  exactly one IdP) on the wildcard or per app. A real decision with real
  lockout risk; revisit once passkeys are enrolled and proven, and decide
  per-app vs fleet. Would also need the `pod_haus_service` module to expose
  `allowed_idps`/`auto_redirect` inputs (currently hardcoded off).
- **Importing the GitHub IdP into Terraform.** It's dashboard-managed today;
  IdPs are otherwise uncoded. Worth importing so identity providers aren't
  half-in-code — but it's a tidy-up, not part of this change.
- **Pocket ID groups for finer authorization.** Authorization stays in
  Cloudflare (`Family`); Pocket ID groups (`groups` scope) are available if
  we ever want IdP-driven authz, not used here.
- **SMTP / LDAP / `UI_CONFIG_DISABLED` hardening.** Not needed for the
  passkey + out-of-band-link flow; can be added later.

---

## Reminders (repo hard rules this touches)

- **No push / `komodo-sync` / `terraform apply` without explicit
  authorization.** `terraform plan` is fine. Every push to main fires the
  deploy procedure.
- **Read the provider docs before the Cloudflare TF** (IdP resource,
  application `allowed_idps`/`auto_redirect`, `cloudflare_ruleset`) — v5
  minors move nested attributes.
- **One consolidated Terraform root**, public endpoints only — the IdP
  resource and module slot into the existing root; nothing host/LAN-pinned.
- **No `deploy = true`**, content-hash label on the service (present),
  absolute bind paths, no per-container `dns:`.
- **`ENCRYPTION_KEY` in 1Password only.** Never commit it; never put it in
  the restic repo. It's the half of the backup that lives apart.
