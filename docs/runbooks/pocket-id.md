# Pocket ID

Self-hosted, passkey-first OIDC identity provider on bilby at `id.pod.haus`.
Pomerium, Forgejo, and the Tailscale account use it for authentication.
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
  `pocket-id:1411`.
- **Tailscale login** uses the client and `tailscale-users` group in
  `terraform/pocket_id.tf`. Caddy serves the required WebFinger response at
  `nathanbaxter.com/.well-known/webfinger`; the IdP selection itself is set in
  the Tailscale console because its Terraform provider doesn't expose it.

## Identity model

Pocket ID is the source of truth for people and their passkeys. On login it issues
an ID token carrying the person's `email` and the names of their `groups`;
Pomerium applies one of three route policies. There is no separate Pomerium user
directory.

| Policy | Who it allows | How Pomerium matches |
|---|---|---|
| Family | The `family` group | `family` in the token's `groups` claim |
| Friends | The `family` and `friends` groups | Either name in the token's `groups` claim |
| Nathan-only | Nathan | His email |

Everyone who uses a protected route must also be in `pomerium-users`, or Pocket
ID refuses the sign-in before any route policy runs.

So authorising someone is group membership in `terraform/pocket_id.tf` and
nothing else: `pomerium-users` to sign in, plus `family` or `friends` for the
routes. The family and friends policies in `pomerium/config.yaml` name no one.
Email is mandatory on a user (`REQUIRE_USER_EMAIL` defaults true), and the
Nathan-only routes and every SSH route match on Nathan's email.

Pomerium refreshes each signed-in person's claims from Pocket ID about every
ten minutes, so a membership added or removed in Terraform reaches the routes
within that time. Signing out at `/.pomerium/sign_out` and in again applies it
at once.

Removing someone's groups does not end what they set up inside Forgejo. An
access token or an SSH key they added there themselves keeps working, because
Forgejo's API and Git SSH don't pass through Pomerium's sign-in. To remove a
person fully, also disable their Forgejo user.

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
| `Pocket ID API Key` | API Credential, `credential` | `data.onepassword_item.pocket_id_api_key` → Pocket ID Terraform provider | users, groups, OIDC clients |
| `Forgejo OIDC` | Login, username + password | Terraform-managed output from `pocketid_client.forgejo` | `forgejo-auth-init` through komodo-op |
| `Pomerium OIDC` | Login, username + password | Terraform-managed output from `pocketid_client.pomerium` | `numbat-pomerium` through komodo-op |
| `Tailscale OIDC` | Login, username + password | Terraform-managed output from `pocketid_client.tailscale` | Tailscale's console-managed IdP registration |

The admin API key is created in the UI (Settings → Admin → API Keys); UI keys
require an expiry (no never-expire, no enforced maximum — pick a far-future
date) and inherit the creating user's privileges.

## OIDC clients

**Pomerium** is confidential, has PKCE disabled, is restricted to
`pomerium-users`, and has callback `https://authenticate.pod.haus/oauth2/callback`. Terraform writes
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
authenticator through Pocket ID after the user resource is created. Pocket ID
sends no mail here, so an administrator creates a one-time login code for the
person from the user list in Pocket ID's admin pages and passes the link on.

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

- `Failed to verify oidc token with fresh keys` — a relying party cannot fetch
  Pocket ID's public JWKS. Check the Numbat relay, Caddy route, and DNS. Never
  put `id.pod.haus` behind Pomerium; OIDC clients must reach its discovery,
  token, and key endpoints.
- **Authenticated, then denied** — on a family or friends route, the person
  isn't in the group the route's policy allows. Fix the membership in
  `terraform/pocket_id.tf`, then have them sign out and in again. On a
  Nathan-only or SSH route, the Pocket ID user's email isn't exactly Nathan's;
  that match is case-sensitive.

## Lockout safety

Pomerium deliberately has one identity provider. A Pocket ID outage blocks new
protected browser and native SSH sessions. Recovery is Numbat's temporary
key-only port 2222, the BinaryLane console, LAN access to bilby, or the explicit
Tailscale SSH recovery plane. Cloudflare Access is not a live Podhaus fallback.

Tailscale's Owner is `nathan@nathanbaxter.com` through Pocket ID. The separate
Tailscale-native `logicwolfe@passkey` Admin remains the recovery path for the
retained tailnet and stays independent of Pocket ID and Terraform.
