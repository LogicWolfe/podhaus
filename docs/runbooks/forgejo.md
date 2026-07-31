---
title: Forgejo
description: Local Git hosting, public SSH relay, backup, and recovery
---

# Forgejo

Forgejo runs on bilby. The browser UI is `https://forge.pod.haus` through
Cloudflare Tunnel + Access. Git SSH uses the ordinary hostname-only URL:

```text
git@git.pod.haus:owner/repository.git
```

That SSH path does not use Cloudflare or Tailscale. `git.pod.haus` is a
DNS-only A record to kookaburra's DigitalOcean Reserved IP. DigitalOcean
delivers that address to the droplet's anchor interface, where rathole listens
on port 22 and forwards to Forgejo's embedded SSH server on bilby. Kookaburra's
own sshd is bound only to the droplet's ordinary public address on port 22.

## Storage

- `/var/lib/forgejo/data` on bilby's NVMe: SQLite, sessions, logs, and runtime
  state.
- `/var/lib/forgejo/config` on bilby's NVMe: generated `app.ini`.
- `/mnt/jump/forgejo`: repositories, LFS objects, attachments, and repository
  archives.

`forgejo-preflight` refuses to start the service unless Jump is mounted, its
sentinel exists, and every required directory is writable. Host directories
and the sentinel are owned by `bilby/host-systemd/install.sh`.

## Accounts and keys

Registration is disabled and repositories default to private. Account and SSH
key state lives under `forgejo/provision/`:

- `users.json` declares each managed account and the 1Password fields that own
  its email and password.
- `keys/<username>/*.pub` declares that person's managed SSH keys.
- `reconcile.sh` converges the declared accounts and keys through Forgejo's
  admin API on every stack deploy.

The reconciler owns keys named `podhaus-managed:*`. It removes a managed key
that disappears from git or whose content drifts. Keys added manually with any
other title are left alone. Account email, password, admin status, active
status, and login restrictions are authoritative too.

Nathan's credentials live in `Forgejo Admin`; Sky's live in
`Forgejo User Sky`. Application secrets come from `Forgejo Secrets`, and the
rathole service token comes from `Rathole Git Relay`.

The `forgejo-admin-init` service exists only for an empty-database recovery,
where the API can't authenticate until the first admin exists.

To refresh Nathan's keys from GitHub:

```bash
gh api users/LogicWolfe/keys --paginate \
  --jq '.[] | [.id,.key] | @tsv'
```

Commit the resulting public keys as
`forgejo/provision/keys/nathan/github-<id>.pub`. Sky's current source key is
`~/.ssh/id_ed25519_sky_access.pub`.

## Checks

```bash
docker inspect --format '{{.State.Health.Status}}' forgejo
docker exec forgejo forgejo doctor check
ssh -T git@git.pod.haus
git clone git@git.pod.haus:OWNER/REPOSITORY.git
```

`ssh -T` should reach Forgejo and report that shell access is disabled. Gatus
checks the internal HTTP health endpoint and the public TCP relay separately.

## Backup

Backrest's `forgejo` plan runs at 03:45 AWST and snapshots the local and Jump
trees together. Its start hook stops Forgejo first because SQLite and repository
data span two filesystems. Its end hook always starts Forgejo again, waits for
health, clears the lock, and reports the result to Gatus.

An ofelia job runs the recovery hook every five minutes. If Backrest is no
longer running restic but the lock remains, it restarts Forgejo and raises a
failed heartbeat. This covers interruption between the stop and end hooks.

## Restore

1. Stop Forgejo: `docker stop --time 60 forgejo`.
2. In Backrest, restore both `/userdata/forgejo/local` and
   `/userdata/forgejo/jump` from the same `forgejo` snapshot into a temporary
   directory.
3. Verify the restore contains `local/data/database/forgejo.db` and the
   expected bare repositories under `jump/repositories`.
4. Move the existing host trees aside, then restore the local tree to
   `/var/lib/forgejo` and the Jump tree to `/mnt/jump/forgejo`.
5. Re-run `sudo ./bilby/host-systemd/install.sh` to assert ownership,
   permissions, and the Jump sentinel.
6. Start the stack, wait for health, run `forgejo doctor check`, then clone and
   `git fsck` a representative repository.

Do not restore only the database or only the repositories. The quiesced
snapshot is the consistency boundary.

Last local restore drill: 2026-07-31. Backrest restored both trees; the restored
SQLite database passed `PRAGMA integrity_check`, and the repository tree and
config were present.

## Kookaburra rebuild

Run Terraform first so the Reserved IP is attached, then run
`./kookaburra_bootstrap`. The SSH hardening script discovers the ordinary and
anchor addresses from DigitalOcean metadata, binds host sshd to the ordinary
address, and reserves anchor port 22 for rathole. Deploy
`kookaburra-relay` and `bilby-relay`, then verify `ssh -T git@git.pod.haus`.

Never make rathole listen on `0.0.0.0:22`: that would collide with or replace
the administrative SSH path.
