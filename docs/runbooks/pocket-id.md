# Pocket ID

Self-hosted, passkey-first OIDC identity provider on bilby at `id.pod.haus`.
Pomerium, Forgejo, and the retained Tailscale account use it for authentication.
Each relying party keeps its own authorisation policy. One Go binary plus
SQLite, single local volume.

> **`id.pod.haus` stays public.** Pomerium and native OIDC clients must reach
> its discovery, token, and key endpoints without first authenticating through
> Pomerium. Pocket ID's own passkey login protects account and admin pages.

## Topology

- **Container** `pocket-id` (v2.x, native arm64) on bilby, on `dockernet`. SQLite
  + uploads under `/app/data` on the local `pocket-id-data` volume (never NFS).
  Internal port `1411`; healthcheck is the image's built-in `pocket-id healthcheck`
  CLI.
- **Ingress** `id.pod.haus` → Numbat public TLS rathole → Caddy `:4444` →
  `pocket-id:1411`. Cloudflare Tunnel and Bypass Access remain for rollback.
- **IdP registration** `cloudflare_zero_trust_access_identity_provider.pocket_id`
  (generic OIDC, PKCE) in `terraform/access.tf`, next to the dashboard-managed
  GitHub IdP. `allowed_idps` is intentionally unset on every Access app, so the
  login chooser lists both GitHub and Pocket ID and the Family group is unchanged.
- **Tailscale login** uses the client and `tailscale-users` group in
  `terraform/pocket_id.tf`. Caddy serves the required WebFinger response at
  `nathanbaxter.com/.well-known/webfinger`; the IdP selection itself is set in
  the Tailscale console because its Terraform provider doesn't expose it.

## Identity model

Pocket ID is the source of truth for people and their passkeys. On login it issues
an ID token carrying the person's `email`; Pomerium applies its Family or
Nathan-only route policy. There is no separate Pomerium user directory.

So authorising someone is two facts that must agree: create them in Pocket ID
with the exact email allowed by `pomerium/config.yaml`. A Pocket ID user whose
email does not match will authenticate and then be denied at the edge.
Email is mandatory on a user (`REQUIRE_USER_EMAIL` defaults true) — without one the
token carries no email claim.

## Load-bearing config

> **`APP_URL` is the WebAuthn relying-party ID — the hostname is permanent.**
> `APP_URL=https://id.pod.haus` is what Pocket ID derives the WebAuthn RP ID and
> origin from. It must stay exactly the public origin (scheme + host, no trailing
> slash). **Changing the hostname invalidates every enrolled passkey.**

- `ENCRYPTION_KEY` — mandatory; encrypts secrets and the signing keys at rest.
  Sourced from 1Password (below).
- Caddy is the only reverse proxy. `TRUST_PROXY=172.18.0.0/16` trusts forwarding
  headers only from dockernet. Rathole does not carry PROXY protocol, so audit
  entries show the relay-side proxy rather than the original internet address.
- Quiet/hardening: `LOG_JSON=true` (Alloy pipeline), `ANALYTICS_DISABLED`,
  `VERSION_CHECK_DISABLED`. `DB_PROVIDER` does not exist in v2 — SQLite is
  auto-detected.

## Secrets

Five 1Password Homelab items use the mechanism that fits each consumer. No
secret is stored in git or a shell env.

| Item | Shape | Consumed as | By |
|---|---|---|---|
| `Pocket ID Encryption Key` | API Credential, `credential` | `OP__KOMODO__POCKET_ID_ENCRYPTION_KEY__CREDENTIAL` (komodo-op) → `ENCRYPTION_KEY` | the container, via `stack.toml` |
| `Pocket ID OIDC` | section `OIDC`: `client id` + `client secret` | `data "onepassword_item"` at plan time (`access.tf`) | Terraform, directly |
| `Pocket ID API Key` | API Credential, `credential` | `data.onepassword_item.pocket_id_api_key` → Pocket ID Terraform provider | users, groups, OIDC clients |
| `Forgejo OIDC` | Login, username + password | Terraform-managed output from `pocketid_client.forgejo` | `forgejo-auth-init` through komodo-op |
| `Pomerium OIDC` | Login, username + password | Terraform-managed output from `pocketid_client.pomerium` | `numbat-pomerium` through komodo-op |
| `Tailscale OIDC` | Login, username + password | Terraform-managed output from `pocketid_client.tailscale` | Tailscale's console-managed IdP registration |

The OIDC client id/secret are read **directly by Terraform** via the
`onepassword` provider data source (`section_map["OIDC"].field_map[…].value`), not
a `TF_VAR`. This is the first data-source consumer of that provider; it needs
`onepassword ~> 3.1` for `section_map`. The admin API key is created in the UI
(Settings → Admin → API Keys); UI keys require an expiry (no never-expire, no
enforced maximum — pick a far-future date) and inherit the creating user's
privileges.

## OIDC clients

**Cloudflare Zero Trust** is confidential, uses PKCE, and has callback
`https://podhaus.cloudflareaccess.com/cdn-cgi/access/callback`. Its credentials
live in `Pocket ID OIDC`. It remains configured only for rollback.

**Pomerium** is confidential, uses PKCE, is restricted to `pomerium-users`, and
has callback `https://authenticate.pod.haus/oauth2/callback`. Terraform writes
its credentials to `Pomerium OIDC` in 1Password.

**Forgejo** is confidential, uses PKCE, and is restricted to `forgejo-users`.
Its credentials live in `Forgejo OIDC`; the remaining identity model is in the
[Forgejo runbook](forgejo.md#identity-and-keys).

**Tailscale** is confidential, has PKCE disabled, is restricted to
`tailscale-users`, and has callback
`https://login.tailscale.com/a/oauth_response`. Its credentials live in
`Tailscale OIDC`.

## Provisioning people and clients

`terraform/pocket_id.tf` is authoritative for Pocket users, groups, group
membership, custom claims and new OIDC clients. Nathan and Sky were imported by
their existing UUIDs, so Terraform adoption preserved their passkeys. Do not
create or edit these objects in the Pocket UI; change Terraform and apply.

Passkeys remain deliberately outside Terraform: a new person enrols their own
authenticator through Pocket ID after the user resource is created.

Forgejo demonstrates the full model. Terraform restricts its client to
`forgejo-users`, maps Nathan through `forgejo-admins`, and publishes each
person's committed public keys as a JSON-array `ssh_keys` custom claim. Forgejo
creates the local profile and synchronizes those keys during OIDC login.

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

## Lockout safety

Pomerium deliberately has one identity provider. A Pocket ID outage blocks new
protected browser and native SSH sessions. Recovery is Numbat's temporary
key-only port 2222, the BinaryLane console, LAN access to bilby, or restoring
the retained Cloudflare DNS and Access path, where GitHub remains a login option.

Tailscale's Owner is `nathan@nathanbaxter.com` through Pocket ID. The separate
Tailscale-native `logicwolfe@passkey` Admin remains the recovery path for the
retained tailnet and stays independent of Pocket ID and Terraform.
