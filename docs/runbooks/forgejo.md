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
A record to Numbat's application address. HTTPS terminates at Pomerium, then
crosses the private mTLS rathole origin to Caddy and Forgejo. Forgejo still uses
Pocket ID natively, so browser login is Pomerium followed by Forgejo OIDC.
Forgejo LFS has an exact public Pomerium route and relies on its short-lived LFS
token. The REST API (`/api/v1`) has a matching public route: Forgejo's own token
auth is the boundary (`REQUIRE_SIGNIN_VIEW` rejects anonymous API calls), which
lets Terraform's forgejo provider manage deploy keys and webhooks from any
machine (`terraform/forgejo.tf`). Port 22 is a separate raw rathole service to
Forgejo's embedded SSH server, so ordinary `git@git.pod.haus` URLs continue to
work.

After Pomerium login, Forgejo shows the Pocket ID button without its marketing
homepage, powered-by label, version, or template timing. This is configuration
in `compose.yaml`, not a template override.

## Storage

- `/var/lib/forgejo/data` on bilby's NVMe: SQLite, sessions, logs, and runtime
  state.
- `/var/lib/forgejo/config` on bilby's NVMe: generated `app.ini`.
- `/mnt/jump/forgejo`: repositories, LFS objects, attachments, and repository
  archives.

`forgejo-preflight` refuses to start the service unless Jump is mounted, its
sentinel exists, and every required directory is writable. Host directories
and the sentinel are owned by the `storage_binds` Ansible role
(`ansible/roles/storage_binds/`).

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

## Actions and application delivery

Actions stays enabled on every repository, including forks and mirrors.
`forgejo/compose.yaml` explicitly includes `repo.actions` in all three
repository-creation defaults and enables Actions globally. After creating or
migrating a repository through the API, verify its `has_actions` field is
`true`; request fields can override creation defaults. A missing workflow or
runner is fixed without disabling Actions.

Forgejo Actions is the CI control plane. Runners are outbound clients on
separate hosts; Forgejo and Bilby's production Docker daemon never execute CI
jobs. The fleet has one runner, on Bandicoot, registered as `bandicoot` for
every repository owned by LogicWolfe. It is provisioned by
`ansible/roles/forgejo_runner` through `ansible/playbooks/bandicoot.yml`:

- `podhaus-ci-x64` runs ordinary Node/Deno container jobs;
- `podhaus-browser-x64` uses the pinned Playwright image;
- both label images are multi-arch and run natively on Bandicoot's aarch64,
  which matches the architecture Komodo builds on Bilby;
- the daemon waits persistently while each job container and network is
  disposable;
- jobs have a one-hour timeout and at most four run at once, set by
  `podhaus_forgejo_runner_capacity`, and the rest queue; Bandicoot's 15 GiB
  is shared with ClickStack, Komodo Core and Fenwick, and a Rust build job
  takes several GiB;
- job containers start with an OOM score adjustment of 900, so when memory
  runs out earlyoom and the kernel kill CI jobs before host services or
  interactive sessions; a job's service containers get the same adjustment;
- job and service containers run privileged, so a job can build its
  repository's Docker image through a `docker:dind` service (see below);
- no Bilby runner exists. A future runner elsewhere must justify itself
  explicitly.

If Bandicoot is unavailable, work queues until it returns; there is no
fallback runner. The daemon reaches Forgejo by pinning `git.pod.haus` to
Bilby's LAN address inside the runner container and its job containers, which
keeps the public hostname for TLS while bypassing Pomerium's browser login
route; Ansible reads the shared address from `config/lan-addresses.json`.
The runner's user registration is durable under `/opt/forgejo-runner/data`,
while Ansible fetches a short-lived registration token from the LogicWolfe
account only for first registration. Repository workflows select the existing
labels, so adding a repository needs no new runner; all repositories share the
job limit and the runner cache. The runner removes disposable job resources,
including each container's anonymous volumes, on completion and its cache
lives under `/opt/forgejo-runner/data/cache`.

CI builds images so that a Dockerfile which cannot build fails the pull
request instead of the Komodo deploy on `main`. A job that builds declares a
`docker:dind` service with TLS turned off, because no volume can carry the
daemon's generated client certificates into the job container, and reaches
it at `tcp://docker:2375` on the per-job network. That daemon and its images
exist only for the job, so every build starts without layer cache.

Privilege is what DinD needs, and it is also root on Bandicoot for any code a
job runs. Bandicoot hosts Komodo Core and 1Password Connect, so a hostile
action reaches the fleet's secrets. Two controls bound that. Job containers
never receive Bandicoot's own Docker socket (`container.docker_host: "-"` and
an empty `valid_volumes`). And every workflow on these labels must pin each
action, `checkout` included, by full commit SHA rather than a tag that can be
moved; an unqualified `actions/checkout@v4` resolves to a movable tag on
`data.forgejo.org`. The pinned form already in use is
`https://data.forgejo.org/actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803`.

These workflows still pin `checkout` by a movable tag and need the SHA form:

- bookcard `.forgejo/workflows/ci.yml`: `actions/checkout@v4` (fix in flight
  in its own pull request);
- dotfiles `.forgejo/workflows/ci.yaml`: `actions/checkout@v6`;
- flood `.forgejo/workflows/check.yml`: `actions/checkout@v4`.

A push to a repository's `main` deploys it: a Forgejo push webhook filtered to
`main` invokes the repository's Komodo procedure, which pulls its managed clone,
syncs the stack definition, and builds and deploys, so what is on `main` is what
is live and no working checkout is an input. Actions runs the checks on pull
requests and on `main`; Komodo performs the native ARM64 image build on the
deploying host. A CI image build is only a check: its image is discarded with
the job, and what runs is always Komodo's build.
Packages remain disabled until a real durable or multi-host artifact need
justifies a registry.

`Forgejo Secrets` owns the application cryptographic secrets. Terraform creates
the `Forgejo OIDC` login item in 1Password from the Pocket client; komodo-op
exports its standard login fields as
`OP__KOMODO__FORGEJO_OIDC__USERNAME` and
`OP__KOMODO__FORGEJO_OIDC__PASSWORD`, and feeds them to the init service.
`Numbat Rathole` owns the SSH relay token.

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

Forgejo runs with a ten-second graceful hammer time. The rathole relay holds an
idle connection on the SSH listener that never drains on its own, so without
that setting Forgejo sat in shutdown until the hook's sixty-second `docker stop`
deadline killed it, and the snapshot read a hard-killed database. The stop now
takes about eleven seconds and Forgejo closes SQLite cleanly first.

Forgejo disables Komodo's stack-state notifications because they cannot
distinguish this expected stop from a fault. Gatus remains the service-health
authority: its two-minute checks require three consecutive failures before
alerting, comfortably exceeding the normal backup stop.

An ofelia job runs the recovery hook every five minutes, at 03:43 and 03:48
either side of the snapshot rather than on the plain five-minute grid, so it
never ticks while the snapshot has Forgejo stopped. It acts only when the lock
has been held longer than fifteen minutes and no restic process is running:
a healthy run holds the lock for about a minute, so anything older belongs to
a run that died between the stop and end hooks. When it does act it restarts
Forgejo and raises a failed heartbeat.

All three subcommands take an exclusive lock on `/data/forgejo-backup.control`
first. The snapshot's own hooks wait for it; the recovery tick gives up
immediately, since there is nothing to recover while a snapshot is running.
That file is never deleted — `/data/forgejo-backup.lock`, which is created and
removed around each snapshot, cannot serve as the exclusion point.

## Restore

1. Stop Forgejo: `docker stop --time 60 forgejo`.
2. In Backrest, restore both `/userdata/forgejo/local` and
   `/userdata/forgejo/jump` from the same `forgejo` snapshot into a temporary
   directory.
3. Verify the restore contains `local/data/database/forgejo.db` and the
   expected bare repositories under `jump/repositories`.
4. Move the existing host trees aside, then restore the local tree to
   `/var/lib/forgejo` and the Jump tree to `/mnt/jump/forgejo`.
5. Re-run `ansible-playbook playbooks/bilby.yml --tags nfs` (from `ansible/`)
   to assert ownership, permissions, and the Jump sentinel.
6. Start the stack. `forgejo-auth-init` reconciles the Pocket source from
   1Password after Forgejo becomes healthy.
7. Run `forgejo doctor check`, sign in through Pocket ID, then clone and
   `git fsck` a representative repository.

Do not restore only the database or only the repositories. The quiesced
snapshot is the consistency boundary.

Last local restore drill: 2026-07-31. Backrest restored both trees; the restored
SQLite database passed `PRAGMA integrity_check`, and the repository tree and
config were present.

## Edge rebuild

Run Terraform to provision Numbat, then run
`ansible-playbook playbooks/numbat-bootstrap.yml` (from `ansible/`, on bilby)
to reconcile the host and outbound Periphery. Komodo deploys `numbat-relay` and
`numbat-pomerium`; `bilby-relay` supplies Forgejo SSH and the private origin.
Verify browser OIDC, LFS, and `ssh -T git@git.pod.haus`.
