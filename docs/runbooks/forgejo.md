---
title: Forgejo
description: Local Git hosting, public SSH relay, backup, and recovery
---

# Forgejo

Forgejo runs on bilby. HTTPS and SSH share one ordinary hostname:

```text
https://git.pod.haus
git@git.pod.haus:owner/repository.git
```

Neither path uses Cloudflare Access or Tailscale. `git.pod.haus` is a DNS-only
A record to kookaburra's DigitalOcean Reserved IP. Public :443 traverses the
existing rathole service to bilby's Caddy, which terminates TLS and proxies to
Forgejo. DigitalOcean delivers Reserved-IP :22 to the droplet's anchor
interface, where rathole forwards it to Forgejo's embedded SSH server. The
droplet sees only TLS ciphertext on :443; its own sshd remains bound to the
ordinary public address on :22.

## Storage

- `/var/lib/forgejo/data` on bilby's NVMe: SQLite, sessions, logs, and runtime
  state.
- `/var/lib/forgejo/config` on bilby's NVMe: generated `app.ini`.
- `/mnt/jump/forgejo`: repositories, LFS objects, attachments, and repository
  archives.

`forgejo-preflight` refuses to start the service unless Jump is mounted, its
sentinel exists, and every required directory is writable. Host directories
and the sentinel are owned by `bilby/host-systemd/install.sh`.

## Identity and keys

Pocket ID is the only interactive identity source. Terraform owns:

- the existing Nathan and Sky Pocket users, imported by UUID so passkeys and
  user identities survive adoption;
- `forgejo-users`, the group allowed to use the confidential Forgejo client;
- `forgejo-admins`, whose members become Forgejo administrators on login;
- the Forgejo OIDC client and its 1Password credential handoff;
- each user's `ssh_keys` custom claim, sourced from `forgejo/keys/`.

Forgejo auto-registers a local profile on the first successful Pocket login.
The OIDC source requires `forgejo-users`, maps `forgejo-admins` to the Forgejo
admin flag, and synchronizes the `ssh_keys` array on every login. Removing a key
from Terraform therefore removes it from Forgejo at the next login. Password
login, HTTP Basic password authentication, account linking, unmanaged
registration and password management are disabled.

The SSH-key page is enabled. Keys synchronized from Pocket are visible there but
remain externally managed: Forgejo won't let someone edit or delete them. A
person can add separate manual keys as an escape hatch. Pocket reconciliation
only replaces keys owned by the Pocket login source, so manual keys survive
future logins. Terraform therefore owns the Pocket subset rather than every key
that may exist on the Forgejo account.

The authentication source itself is a Forgejo database object and has no
Terraform resource. The `forgejo-auth-init` one-shot converges that single
object using Forgejo's supported `admin auth {add,update}-oauth` CLI. User and
key reconciliation does not happen in a custom script.

`Forgejo Secrets` owns the application cryptographic secrets. Terraform creates
the `Forgejo OIDC` login item in 1Password from the Pocket client; komodo-op
exports its standard login fields as
`OP__KOMODO__FORGEJO_OIDC__USERNAME` and
`OP__KOMODO__FORGEJO_OIDC__PASSWORD`, and feeds them to the init service.
`Rathole Git Relay` owns the SSH relay token.

To refresh Nathan's keys from GitHub:

```bash
gh api users/LogicWolfe/keys --paginate \
  --jq '.[] | [.id,.key] | @tsv'
```

Commit the resulting public keys as
`forgejo/keys/nathan/github-<id>.pub`. Sky's current source key is
`~/.ssh/id_ed25519_sky_access.pub`. Run Terraform after changing a key claim;
the affected user then logs in once to make Forgejo synchronize it.

## Checks

```bash
docker inspect --format '{{.State.Health.Status}}' forgejo
docker exec forgejo forgejo doctor check
curl -fsS https://git.pod.haus/api/healthz
ssh -T git@git.pod.haus
git clone git@git.pod.haus:OWNER/REPOSITORY.git
```

`ssh -T` should reach Forgejo and report that shell access is disabled. Gatus
checks internal HTTP, public HTTPS and public SSH separately.

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
6. Start the stack. `forgejo-auth-init` reconciles the Pocket source from
   1Password after Forgejo becomes healthy.
7. Run `forgejo doctor check`, sign in through Pocket ID, then clone and
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
