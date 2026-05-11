# Periphery v2 keypair auth migration

Both bilby's and kangaroo's Komodo Periphery agents currently use the
**legacy `KOMODO_PASSKEY` shared-secret** model. Phase 15a (kangaroo
bring-up) deliberately stayed on the passkey path so there'd be exactly
one moving part at a time. This is the focused single-purpose change to
move both Peripheries onto **v2 noise-handshake keypair auth**.

## Why now

- Passkey is the deprecated path; upstream is moving to v2 by default.
- A leaked passkey trivially gates Core ↔ Periphery — keypair auth
  raises the bar.
- Cleaner story for adding pinelake or any future host: generate a
  keypair, paste the pubkey into Core's per-Server config, done.

## What changes

Periphery side (each host's `periphery.config.toml`):

```toml
private_key = "<periphery private key>"
core_public_keys = ["<core pubkey>"]
# remove the KOMODO_PASSKEYS env entry from compose
```

Core side (`komodo/compose.env` + per-Server config in `servers.toml`):

```toml
[[server]]
name = "kangaroo"
[server.config]
address = "https://10.0.0.25:8120"
periphery_public_key = "<kangaroo's pubkey>"
```

```env
# komodo/compose.env
KOMODO_CORE_PRIVATE_KEY=<core private key>
# remove KOMODO_PASSKEY
```

## Open question (resolve before cutover)

Whether passkey + v2 can **coexist on a single Periphery during
cutover** is unclear from upstream docs. Two possible cutover models:

1. **Coexistent** — Periphery accepts either passkey or keypair; Core
   tries keypair first, falls back to passkey. Allows a soak period.
2. **One-shot** — Periphery accepts exactly one auth model at a time;
   cutover requires a coordinated restart of Core + both Peripheries.

Plan for the one-shot model (safer if the answer is unknown):

## Cutover runbook (one-shot)

1. **Generate keypairs** ahead of time:
   - Periphery autogen on first start with the new config; alternatively
     pre-generate via `openssl` and place at
     `${root_directory}/keys/periphery.key`.
   - Core ditto.
2. **Stash pubkeys in 1P** for the future-host onboarding case:
   `op://Homelab/Komodo Core Public Key/notesPlain`,
   `op://Homelab/Komodo Periphery Bilby Public Key/notesPlain`,
   `op://Homelab/Komodo Periphery Kangaroo Public Key/notesPlain`.
3. **Render configs** with `op run` on bilby, ship the kangaroo one
   via `kangaroo_bootstrap`'s scp path.
4. **Verify configs locally first** — `docker compose config` on each
   stack to confirm interpolation worked.
5. **Cutover window** — bilby Core down, kangaroo Periphery down, bilby
   Periphery down. Swap configs. Bring Core up. Bring both Peripheries
   up. Watch logs.
6. **Verify** — `komodo-status`, Komodo UI shows both Servers as `Ok`,
   `./komodo-sync` succeeds.

## Revert path

Single-purpose: re-add the `KOMODO_PASSKEY` env to Core, re-add
`KOMODO_PASSKEYS` to both Peripheries' compose, restart all three.
The kangaroo_bootstrap script already supports the passkey path so
re-rendering the kangaroo config is a one-liner.

## Out of scope

- Migrating bilby off `files_on_host` to Linked Repo — explicitly kept
  as a mixed model: bilby = active dev (files_on_host), kangaroo =
  push-to-deploy (Linked Repo).
- Webhook auto-deploy for kangaroo stacks — available via Linked Repo
  + GitHub webhook, separate quality-of-life follow-up. Tracked in
  [Deferred follow-ups](deferred-followups.md).

## Reference

Upstream docs are sparse on whether passkey + v2 coexist. The 2026-05-01
parallel-research dispatch surfaced the field names
(`private_key`, `core_public_keys`, `periphery_public_key`,
`onboarding_key`) but didn't resolve the coexistence question — that
answer comes from testing during the cutover window.
