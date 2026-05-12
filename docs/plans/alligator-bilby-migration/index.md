# Alligator → Bilby migration

Migration of all running services from `alligator` (Intel NUC, x86_64) to
`bilby` (Apple M1 Mac mini, aarch64, Asahi Linux), with kangaroo (QNAP NAS)
joining mid-flight as a second managed host under one Komodo Core.

The core work is done — **alligator was powered off 2026-04-14**, every
service has lived on bilby/kangaroo since, and the Docker-based + Komodo-
managed + 1Password-backed architecture has been stable for weeks. What
remains is end-of-project polish: one auth-model swap, two Railway services
not yet migrated, and a handful of non-blocking follow-ups.

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

Four streams, all independent.

1. [**Periphery v2 keypair auth**](periphery-v2-auth.md) — migrate
   bilby's + kangaroo's Periphery agents off the legacy
   `KOMODO_PASSKEY` shared-secret model onto v2 noise-handshake keypair
   auth. Single-purpose change, single revert path.
2. [**Paperless email ingest**](paperless-email-ingest.md) — set up
   Fastmail alias + IMAP-polling Paperless mail account so anything
   forwarded to `paperless@<domain>` lands in the archive
   automatically. The compose-level `PAPERLESS_EMAIL_TASK_CRON` is
   already wired; just needs the alias + folder + app password +
   Paperless mail rule.
3. [**Railway migrations**](railway-migrations.md) — bring doggos
   (kid's static site) and yiayia (board app) home from Railway. The
   Komodo webhook bypass Access app is already in place (TF-managed)
   and the auto-deploy webhook + GitHub-side hook are live too.
4. [**Deferred follow-ups**](deferred-followups.md) — non-blocking
   items surfaced during the migration: NFS bind-mount auto-recovery,
   ofelia self-restart workaround removal pending upstream PR,
   host-package runbook, orphan-container behaviour documentation,
   komodo-start first-boot API-key automation, the upstream komodo-op
   PR.

[Paperless stabilization](paperless-stabilization.md) is **done**
(2026-05-12). See [Completed work](completed-work.md) for the recap.

[Terraform foundation](terraform-setup.md) and
[Cloudflare as Terraform](cloudflare-terraform.md) are **done**.
Steady-state docs live at [Terraform](/terraform.html). Summary of
what landed: MinIO state backend, `./tf` runner, full Cloudflare
migration (11 zones / ~82 DNS records / 15 Access apps / 2 service
tokens / TF-managed tunnel config), per-service module
(`cloudflare/modules/pod_haus_service`), UniFi DNS via TF,
DNSControl retired in full, GitHub webhook driving Komodo
push-to-deploy, smart `komodo-sync`, Komodo→Gatus deploy-failure
alerting. See [Completed work](completed-work.md) for the chronological
recap.

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
