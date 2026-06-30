# Pocket ID

Self-hosted, passkey-first OIDC identity provider on bilby at `id.pod.haus`. It
is wired into Cloudflare Access as a login method *alongside* the existing GitHub
login — Cloudflare Access (the Family group) stays the authority on *who* is
allowed; Pocket ID only provides *authentication* (WebAuthn passkeys). One Go
binary plus SQLite, single local volume.

> **`id.pod.haus` must stay publicly reachable — it is NOT Access-gated.**
> Cloudflare validates the OIDC token *server-side*: during a login its own
> servers fetch `/api/oidc/token` and `/.well-known/jwks.json` from `id.pod.haus`,
> so those must be reachable with no Access policy in the way. `id.pod.haus`
> therefore has a **Bypass-everyone** Access app (`module.pocket_id`,
> `access_policy_ids = [public_bypass]`) that overrides the `*.pod.haus` Family
> gate — the same mechanism as `sky`/`unifi`. A Family-gated `id.pod.haus`
> deadlocks with `Failed to verify oidc token with fresh keys`. Pocket ID's own
> passkey login protects the admin UI, so a public edge is correct here.

## Topology

- **Container** `pocket-id` (v2.x, native arm64) on bilby, on `dockernet`. SQLite
  + uploads under `/app/data` on the local `pocket-id-data` volume (never NFS).
  Internal port `1411`; healthcheck is the image's built-in `pocket-id healthcheck`
  CLI.
- **Ingress** `id.pod.haus` → tunnel → `http://pocket-id:1411`, via
  `module.pocket_id` in `terraform/services_pod_haus.tf` (DNS + the Bypass Access
  app + tunnel ingress rule).
- **IdP registration** `cloudflare_zero_trust_access_identity_provider.pocket_id`
  (generic OIDC, PKCE) in `terraform/access.tf`, next to the dashboard-managed
  GitHub IdP. `allowed_idps` is intentionally unset on every Access app, so the
  login chooser lists both GitHub and Pocket ID and the Family group is unchanged.

## Identity model

Pocket ID is the source of truth for people and their passkeys. On login it issues
an ID token carrying the person's `email`; Cloudflare matches that email against
the **Family** group in `access.tf` and allows or denies. There is no separate
Cloudflare user directory.

So authorising someone is two facts that must agree: create them in Pocket ID
*with an email the Family policy already matches* (Family covers
`@nathanbaxter.com`, `@pod.haus`, and `scroeser@gmail.com`). A Pocket ID user
whose email doesn't match will authenticate and then be *denied* at the edge.
Email is mandatory on a user (`REQUIRE_USER_EMAIL` defaults true) — without one the
token carries no email claim.

## Load-bearing config

> **`APP_URL` is the WebAuthn relying-party ID — the hostname is permanent.**
> `APP_URL=https://id.pod.haus` is what Pocket ID derives the WebAuthn RP ID and
> origin from. It must stay exactly the public origin (scheme + host, no trailing
> slash). **Changing the hostname invalidates every enrolled passkey.**

- `ENCRYPTION_KEY` — mandatory; encrypts secrets and the signing keys at rest.
  Sourced from 1Password (below).
- Behind cloudflared: `TRUST_PROXY=true` + `TRUSTED_PLATFORM=cf-connecting-ip`
  (correct client IP in the audit log). TLS terminates at the Cloudflare edge — no
  cert config in the container.
- Quiet/hardening: `LOG_JSON=true` (Alloy pipeline), `ANALYTICS_DISABLED`,
  `VERSION_CHECK_DISABLED`. `DB_PROVIDER` does not exist in v2 — SQLite is
  auto-detected.

## Secrets

Three 1Password Homelab items, each consumed by the mechanism that fits its
consumer — no secret in git or a shell env.

| Item | Shape | Consumed as | By |
|---|---|---|---|
| `Pocket ID Encryption Key` | API Credential, `credential` | `OP__KOMODO__POCKET_ID_ENCRYPTION_KEY__CREDENTIAL` (komodo-op) → `ENCRYPTION_KEY` | the container, via `stack.toml` |
| `Pocket ID OIDC` | section `OIDC`: `client id` + `client secret` | `data "onepassword_item"` at plan time (`access.tf`) | Terraform, directly |
| `Pocket ID API Key` | API Credential, `credential` | read ad-hoc via the service-account token | provisioning |

The OIDC client id/secret are read **directly by Terraform** via the
`onepassword` provider data source (`section_map["OIDC"].field_map[…].value`), not
a `TF_VAR`. This is the first data-source consumer of that provider; it needs
`onepassword ~> 3.1` for `section_map`. The admin API key is created in the UI
(Settings → Admin → API Keys); UI keys require an expiry (no never-expire, no
enforced maximum — pick a far-future date) and inherit the creating user's
privileges.

## The OIDC client

A single Pocket ID OIDC client named **Cloudflare Zero Trust**: confidential
(`isPublic=false`), PKCE enabled, callback
`https://podhaus.cloudflareaccess.com/cdn-cgi/access/callback`. Its client
id/secret live in the *Pocket ID OIDC* 1P item and are consumed by the Cloudflare
IdP resource — Cloudflare's stored `redirect_url` must equal that callback.

## Provisioning people

Via the admin API (header `X-API-Key`), or the equivalent UI. Each person opens a
one-time link and enrols their own passkey — passkeys can't be enrolled for them.

```sh
# create a user (email must match a Family rule)
curl -X POST https://id.pod.haus/api/users -H "X-API-Key: $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"username":"sky","email":"scroeser@gmail.com","firstName":"Sky","lastName":"Croeser"}'

# mint a one-time passkey-enrolment link (ttl default 15m, max 31d)
curl -X POST https://id.pod.haus/api/users/<id>/one-time-access-token \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d '{"ttl":"168h"}'
# -> {"token":"…"}  →  hand out https://id.pod.haus/lc/<token> out of band
```

## Backup & restore

> **A restore needs the same `ENCRYPTION_KEY`.** backrest snapshots the
> `pocket-id_pocket-id-data` volume nightly (`backup/bilby`) — the SQLite db +
> uploads. The encryption key is the other half of every backup: it lives in
> 1Password, never in the restic repo. A backup restored under a different key
> leaves the encrypted columns (signing keys, secrets) unreadable. Restore the
> volume (file), or `pocket-id import --path <zip> --yes` then restart (logical).

## Failure modes

- `Failed to verify oidc token with fresh keys` — Cloudflare can't fetch the
  JWKS: `id.pod.haus` got Access-gated, Bot Fight Mode is on for the zone, or a WAF
  rule is blocking Cloudflare's egress (ASN `13335`). Keep `id.pod.haus` on the
  Bypass-everyone app and Bot Fight Mode off; if needed, a WAF skip rule for
  AS13335 on `id.pod.haus` (mirror the `cloudflare_ruleset` shape in
  `umami_analytics.tf`).
- **Authenticated, then denied** — the Pocket ID user's email doesn't match the
  Family group. Fix the email in Pocket ID; the match is case-insensitive but
  otherwise exact.

## Lockout safety & going passkey-only

GitHub login stays configured (`allowed_idps` unset everywhere), so a Pocket ID
outage or misconfiguration does *not* lock you out — log in via GitHub to reach
`komodo.pod.haus` and fix it. The Homelab service token also still bypasses for
automation.

Making login skip the chooser and go straight to a passkey
(`auto_redirect_to_identity = true`) requires `allowed_idps` to list exactly one
provider — which would disable the GitHub fallback for that app. That is a
deliberate, reversible change to make per-app (and would need the
`pod_haus_service` module to expose `allowed_idps`/`auto_redirect`, currently
hardcoded off); enrol a passkey and prove the login first.
