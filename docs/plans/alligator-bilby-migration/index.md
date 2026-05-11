# Alligator → Bilby migration

Migration of all running services from `alligator` (Intel NUC, x86_64) to
`bilby` (Apple M1 Mac mini, aarch64, Asahi Linux), with kangaroo (QNAP NAS)
joining mid-flight as a second managed host under one Komodo Core.

The core work is done — **alligator was powered off 2026-04-14**, every
service has lived on bilby/kangaroo since, and the Docker-based + Komodo-
managed + 1Password-backed architecture has been stable for weeks. What
remains is end-of-project polish: one auth model swap, a documentation
cleanup window for the Paperless import, Cloudflare-as-code via Terraform,
two Railway services not yet migrated, and a handful of non-blocking
follow-ups.

## Status

- **alligator** — powered off, DNS removed.
- **bilby** — Komodo Core + every original podhaus stack, all healthy.
- **kangaroo** — second Periphery, Syncthing, second Backrest, autoheal,
  logging. Joined the deployment 2026-05-01.
- **pinelake** — planned third host; no infrastructure landed yet.

For day-to-day operating guidance see the rest of the docs site:
[Architecture](/architecture.html), [Hosts](/hosts.html),
[Komodo](/komodo.html), [Stack conventions](/stack-conventions.html).
This plan is the historical record + the punch list for what's left.

## Completed work

See [Completed work](completed-work.md) for the full chronological
summary — Komodo bootstrap, the Phase 6 architecture pivot,
stack-by-stack migrations, the OneNote → Paperless bulk import,
alligator retirement, kangaroo bring-up, and the 2026-05-11
documentation overhaul.

## Remaining work

Six streams. #3 → #4 → #5 is the only hard dependency chain; everything
else is independent.

1. [**Periphery v2 keypair auth**](periphery-v2-auth.md) — migrate
   bilby's + kangaroo's Periphery agents off the legacy
   `KOMODO_PASSKEY` shared-secret model onto v2 noise-handshake keypair
   auth. Single-purpose change, single revert path.
2. [**Paperless stabilization**](paperless-stabilization.md) — close
   out the OneNote bulk-import work: `unknown` bucket review, delete
   stale `$value` files from the export tree, hard-delete Paperless
   Trash, commit the final sidecar DB.
3. [**Terraform foundation**](terraform-setup.md) — stand up a
   single-node MinIO stack on bilby and a `tf` runner wrapper so any
   future Terraform work has a state backend with native locking and a
   Backrest plan. Prerequisite for #4.
4. [**Cloudflare as Terraform**](cloudflare-terraform.md) — replace
   DNSControl + the planned cf-access-sync tool with a single Terraform
   surface covering Access, DNS, Rulesets, Transform Rules, Cache
   Rules. Consumes #3's state backend; unblocks the Railway-migrations
   webhook-bypass work below.
5. [**Railway migrations**](railway-migrations.md) — bring doggos
   (kid's static site) and yiayia (board app) home from Railway. Needs
   the Terraform Access Application from #4 for the Komodo webhook
   bypass.
6. [**Deferred follow-ups**](deferred-followups.md) — non-blocking
   items surfaced during the migration: NFS bind-mount auto-recovery,
   ofelia self-restart workaround removal pending upstream PR,
   host-package runbook, komodo-sync auto-deploy gap, orphan-container
   behaviour documentation, komodo-start first-boot API-key automation.

## Credentials

All five credentials are in 1Password Homelab and surface as Komodo
Variables via komodo-op. Plex token is consumed by the Plex Preferences
init container; rclone OneDrive token is the one exception still
rendered host-side by komodo-start (multi-line OAuth blob doesn't fit
Komodo's env-file pipeline).

| Item | 1Password field | Purpose |
|---|---|---|
| `railway-api-token` | `credential` | Railway projects (Kuma, doggos, yiayia) |
| `postmark-smtp` | `username`, `credential`, `server`, `port` | Backup + alert notifications |
| `restic-repo-password` | `credential` (48-char base64) | Restic repo encryption |
| `Plex Online Token` | `credential` | Plex.tv claim token |
| `rclone-onedrive-token` | `notesPlain` (Secure Note) | Off-site restic sync |
