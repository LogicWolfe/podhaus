# Host provisioning

How a podhaus host gets from a bare OS to a working member of the fleet.

Two tools own two disjoint halves of a machine, and the split is the
whole design:

| Layer | Tool | Owns | Runs as |
|---|---|---|---|
| Machine | **Ansible** (`ansible/`) | Everything outside `$HOME`: packages, systemd, Docker, sshd, Komodo Periphery | root, from a control node |
| User | **chezmoi** (`~/repos/dotfiles`) | Everything inside `$HOME`: shell, dotfiles, editor, SSH client config, machine key | the user, on the machine |

The boundary is **root state vs user state**, not infrastructure vs
personal. It is drawn there because it is the only line that stays
crisp: anything needing `sudo` is Ansible's, anything that doesn't is
chezmoi's. The practical consequence is that **chezmoi never prompts for
a password**.

A host can take both. fractal does — it is a podhaus host *and* Nathan's
development machine, so Ansible gives it Docker and Periphery while
chezmoi gives it fish and dotfiles. Neither layer knows about the other,
and `playbooks/fractal.yml` deliberately does **not** invoke chezmoi:
that would put user state under root's control and dissolve the boundary
the layer exists to draw.

## Cross-host state: one producer, one channel, zero copies

Every piece of state that crosses hosts follows one rule set:

- **One producer.** Values Terraform generates (PKI, addresses, tokens)
  live in Terraform state and nowhere else. Values a host generates
  (Forgejo's host key, Periphery private keys) stay on the host that
  made them, with only the public half committed or documented.
- **One channel.** 1Password is the only distribution path for anything
  that crosses hosts. Terraform publishes there; Ansible reads there
  (`community.general.onepassword` lookups run on the control node, so
  targets need no op auth); chezmoi reads there via `op-homelab`.
- **Zero copies.** The repo carries no file whose content is derivable
  from Terraform state. The narrow exception is a root-of-trust literal
  a fresh machine needs before it can reach any channel — the Forgejo
  host key in the dotfiles README, and the Pomerium SSH host-key
  fingerprint there for human TOFU verification on non-homelab machines.
- **Terraform feeds, never drives.** `terraform apply` never runs
  playbooks: provisioners are invisible to `plan` (breaking the
  from-anywhere contract), a failed playbook would taint and replace the
  resource it ran on, and most of the fleet is not TF-created. Its job
  ends at publishing values; templating its own outputs into cloud-init
  at create time (numbat) is fine. Host state changes when a human runs
  a playbook.

The resulting ledger:

| Value | Producer | Channel | Consumers |
|---|---|---|---|
| Pomerium SSH user CA (public) | TF `tls_private_key.pomerium_ssh_user_ca` | 1P `Pomerium Secrets` | `sshd_pomerium_ca` role; numbat cloud-init (TF-direct); `kangaroo_bootstrap` (op read on the bilby side) |
| Pomerium SSH host key (public) | TF `tls_private_key.pomerium_ssh_host` | 1P `Pomerium Secrets` | chezmoi `00-ssh-hostkeys` upsert; README fingerprint for TOFU |
| numbat application + relay IPv4 | TF (BinaryLane) | 1P numbat handoffs | numbat host_vars → nft/dispatcher templates |
| numbat host SSH key | TF `tls_private_key.numbat_ssh_host` | 1P (public half) | numbat bootstrap play pins first contact |
| Rathole tokens, noise keys | TF `random_password` | 1P `Numbat Rathole` | relay `.env` renders via lookup |
| Per-host log-shipping mTLS certs | TF `voltaire_log_client` etc. | 1P `Log Ingest PKI` | logging stacks via Komodo variables |
| Periphery X25519 private keys | generated on bilby | `/opt/komodo/keys` on the control node only | `komodo_periphery` role |
| Forgejo SSH host key | Forgejo container | committed literal in dotfiles (root of trust) | chezmoi `00-ssh-hostkeys` |

## Which hosts Ansible manages

**fractal**, **bilby**, **numbat**, and **voltaire** — the `provisioned`
group, which is what `site.yml` targets. How each is reached is a
per-host fact in `host_vars/`: bilby is the control node and runs
against itself (`ansible_connection: local`); fractal is direct on the
home LAN (`10.0.0.70`, the Windows host's `:22` forward); numbat and
voltaire have no inbound path of their own and route through Pomerium,
carrying `nathan@numbat` / `nathan@voltaire` as `ansible_user` — that is
a Pomerium *route selector*, not an OS account, which is why
OS-account work uses the separate `podhaus_operator` var.

**kangaroo is not an Ansible target and never will be** — QTS ships no
Python interpreter, so `kangaroo_bootstrap` is its permanent supported
path. Nathan's MacBook is not in the inventory either: it is a personal
device with chezmoi only, not infrastructure.

## Layout

```text
ansible/
  ansible.cfg              control-node config
  requirements.yml         collection pins (community.general, community.docker)
  inventory/
    hosts.yml              the whole fleet, grouped by state and by role
    group_vars/all.yml     fleet-wide facts (timezone, dockernet)
    host_vars/<host>.yml   per-host facts
  playbooks/
    site.yml               targets the `provisioned` group
    fractal.yml            single-host entry point
    bilby.yml              single-host entry point (+ Komodo host dirs)
    numbat.yml             single-host entry point (steady state)
    numbat-bootstrap.yml   fresh-VM bring-up, sequencing preserved as play order
  roles/
    base/                  timezone, baseline packages, dirs
    wsl/                   /etc/wsl.conf, hostname
    docker/                engine (where managed), daemon.json, host networks
    devbox/                the root-requiring half of a developer machine
    komodo_periphery/      keys, compose, and a wait-for-Ok gate
    sshd_pomerium_ca/      trust Pomerium's SSH user CA
    nfs_binds/             QNAP NFS-bind hardening (bilby)
    firewalld/             declarative zone + service XML (bilby)
    komodo_core_host/      Komodo Core's host directories (bilby)
    numbat_edge/           numbat's nftables ruleset, relay-IP dispatcher, loopback sshd
```

### Inventory groups

Hosts are grouped twice: by **whether Ansible manages them**, and by
**role**.

- `provisioned` — the Ansible-owned hosts: fractal, bilby, numbat, and
  voltaire. `site.yml` targets this group and nothing else, gating each
  role (including single-host ones like `nfs_binds`, `firewalld`, and
  `numbat_edge`) on the matching role group rather than on hostname, so a
  new host inherits the right roles from group membership alone.
- `excluded` — kangaroo. QTS ships no Python interpreter at all (no
  `python3`, no `/opt/bin/python3`, only the MalwareRemover and
  Container Station QPKGs), so it can never be an Ansible target.
  `kangaroo_bootstrap` is permanent, not interim. It is listed here
  rather than omitted so the inventory shows the whole fleet, with
  `ansible_host: unreachable.invalid` so a stray `--limit` can't dial it.
- `docker_hosts`, `komodo_periphery_hosts`, `devboxes`, `edge_hosts`,
  `komodo_core_hosts`, `nfs_binds_hosts`, `firewalld_hosts` — role
  groups. `site.yml` gates each role on membership.

## Running it

Ansible is a control-node dependency only; nothing is installed on
targets beyond a Python interpreter, which Fedora already has. It lives
in the repo's `.venv`.

```sh
cd ansible
ansible-playbook playbooks/fractal.yml --check --diff   # read first
ansible-playbook playbooks/fractal.yml
```

Authentication is the op-unlock agent — `group_vars/all.yml` passes
`IdentityAgent` through from `$SSH_AUTH_SOCK`, so the same unlock that
lets you `ssh` a host lets Ansible reach it. No key material is
configured anywhere in the layer.

> **Ansible is not wired into push-to-deploy.** The GitHub webhook fires
> `podhaus-push-deploy`, which touches Komodo stacks only. Host state
> changes when a human runs a playbook, deliberately. Pushing a role
> edit deploys nothing.

Idempotency is the contract, and it is checked by machine rather than
asserted: a second run of `playbooks/fractal.yml` reports `changed=0`
across every task. Treat a non-zero second run as a bug in the role.

**Read `--check --diff` before every real run against a host that is
already carrying load**, and audit each reported delta — an unexplained
change on a live host is the signal that a role has drifted from what
the machine actually runs. Verify the result with a config-level signal
per subsystem (Komodo reporting `state=Ok`, rathole control channels
established, `sshd -T`), never "the container is healthy": a container
being up proves it started, not that it is doing its job.

## Roles worth knowing about

**`base`** opens with a `raw` task that installs `python3-libdnf5` if
missing. This is the one deliberate `check_mode: false` in the layer:
without those bindings `--check` fails outright rather than reporting a
diff, so the task installs a read-only prerequisite *of the dry run
itself*. Everything after it is a normal module.

**`docker`** owns the engine only where
`podhaus_docker_engine_managed` is true — bilby runs Fedora's
moby-engine (pre-existing state; an engine swap is out of scope), so
there the role manages only daemon config and networks. `daemon.json`
is a template whose byte layout is load-bearing: on a host without
live-restore active, the restart handler bounces every container, so
the `podhaus_docker_live_restore: false` render must byte-match bilby's
live file, and flipping bilby to true is a scheduled human act, never a
handler side effect. The dockernet task deliberately leaves
`attachable` unspecified (`docker_network` recreates a network over any
specified-and-different option — fatal on a live host), and
`podhaus_extra_networks` declares label-only bridges (bilby's fenwick
nets) whose auto-assigned subnets must stand. The role installs
`python3-requests` because `community.docker.docker_network` needs it
on the target; the alternative — a `docker network inspect || create`
shell line — would have forfeited idempotency and check-mode diffs to
save one package. `daemon.json` deliberately carries **no `dns:` key**;
per-container DNS overrides replace Docker's embedded resolver and
break service-name resolution, so DNS forwarding is a daemon-wide
setting where a host needs it.

**`nfs_binds`** carries bilby's postmortem-hardened NFS defences: the
pre-dockerd QNAP reachability gate, the automount `StartLimit*=0`
drop-ins, the `chattr +i` tripwire on the bare mountpoints (a `script:`
task — the non-recursive `mount --bind /` trick has no Ansible
primitive — with an honest `changed_when` on its output), the
`.podhaus-share-mounted` sentinels (touched with
`modification_time: preserve` so re-runs stay `changed=0`), and the
Forgejo directory ownership. The role header carries the incident
history; the postmortems are the full record.

**`firewalld`** stages the declarative zone + service XML from role
files — services before the zone, so the zone never references an
undefined service — validates with `firewall-cmd --check-config` on
every run, and reloads via handler only after validation passes. It
fails fast if firewalld is absent rather than skipping.

**`komodo_periphery`** ships the host's X25519 private key (`no_log`,
mode 0600) and Core's public key, renders `periphery.config.toml`,
brings the container up, and then **polls Core's `ListServers` API until
the Server reports `Ok`**. That last gate is the point: a Periphery
container being healthy proves only that it started, not that Core
trusts its key or can reach it. The playbook fails if the handshake
doesn't complete.

Periphery is deliberately *not* Komodo-managed on any outbound host —
Core reaches the host only through the connection Periphery makes, so a
Komodo-driven redeploy of it would sever the path it runs on. Ansible
owns it instead of a bootstrap script.

**`sshd_pomerium_ca`** writes a drop-in under `sshd_config.d/` rather
than editing `sshd_config`, validates the file with `sshd -t -f %s`,
re-checks the *combined* config afterwards, and **reloads rather than
restarts**. A reload does not drop established connections, so the
session running the playbook survives a bad edit long enough to fix it.

**`numbat_edge`** is numbat's host-specific edge: the dual-address
nftables ruleset and the NetworkManager dispatcher that keeps the relay
IP on `eth0` are jinja templates fed from host_vars, whose two addresses
are 1Password lookups against the fields Terraform publishes (never DNS,
never `terraform output`). It also owns the loopback-only sshd drop-in,
cockpit removal, the SELinux label for first-boot port 2222, and the
guest agent. Activation of a changed ruleset is a handler gated on
`podhaus_numbat_firewall_apply`, which exists for one consumer:

## numbat: two plays

numbat is a remote, self-firewalling host, so its bring-up is
*sequencing* — preserved in `playbooks/numbat-bootstrap.yml` as task
order, each constraint commented. The play runs **from bilby** (it
streams Periphery keys from `/opt/komodo/keys` and polls Core on
localhost), connects to the application IP on first-boot port 2222 with
the host key pinned from 1Password, stages the `numbat_edge` config
*without* loading the final ruleset (it would close 2222, the play's own
transport), punches only the relay ports into the live bootstrap table,
starts the rathole relay **before** Periphery (Periphery dials
`core-connect.pod.haus`, which resolves back through this host's own
relay), enrolls the Tailscale recovery daemon, and closes 2222 last —
scheduling the stop of the bootstrap sshd three seconds after the play
disconnects.

The bootstrap play is only truly exercised by an actual rebuild, and
that is left as-is deliberately. Forcing an exercise of it means
`terraform apply -replace=binarylane_server.numbat`, and numbat's two
public IPv4s come from `public_ipv4_count` on the server resource — they
are allocated per-VM, with no reserved or floating IP in front — so a
replace lands two new addresses and a real production DNS cutover across
every record derived from them, plus a Pomerium Autocert cache that is
not preserved. The play gets its real test the day numbat actually needs
rebuilding; the runbook for that is
[Fresh Numbat from scratch](disaster-recovery.html#numbat-rebuild).

`playbooks/numbat.yml` is the steady state — base, docker, numbat_edge,
sshd_pomerium_ca, komodo_periphery — reached through Pomerium like any
managed host, and the thing check-mode equivalence proves against the
live gateway.

## Adding a host

See [Hosts → Adding another host](hosts.html#adding-host) for the
end-to-end sequence including the Komodo-side resources.
