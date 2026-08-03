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
a password**. Its macOS branch was already sudo-free; the Linux branches
move under Ansible as each host migrates.

A host can take both. fractal does — it is a podhaus host *and* Nathan's
development machine, so Ansible gives it Docker and Periphery while
chezmoi gives it fish and dotfiles. Neither layer knows about the other,
and `playbooks/fractal.yml` deliberately does **not** invoke chezmoi:
that would put user state under root's control and dissolve the boundary
the layer exists to draw.

## What is Ansible-managed today

**fractal** is fully migrated (`provisioned`). **bilby** has a complete
playbook — `playbooks/bilby.yml` covers its Docker daemon config and
networks, the NFS-bind hardening, the firewall, the Pomerium CA trust,
and Komodo Core's host directories — but stays in `pending_migration`
until its live check-mode equivalence pass comes back clean; that pass,
the real run, and the scheduled live-restore flip are deliberate human
acts. **numbat**'s two plays exist and its bootstrap script is gone; it
likewise joins `provisioned` once its live check-mode pass comes back
clean. voltaire is still owned by hand and kangaroo by its bootstrap
script. See
[the migration plan](plans/host-provisioning-migration.md) for what
is left.

## Layout

```
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
    numbat_edge/           numbat's nftables ruleset, relay-IP dispatcher, loopback sshd
```

### Inventory groups

Hosts are grouped twice: by **migration state** and by **role**.

- `provisioned` — fully Ansible-owned. Currently fractal alone.
  `site.yml` targets this group and nothing else.
- `pending_migration` — bilby, numbat, voltaire. Present so
  the inventory is honest about the fleet. bilby's and numbat's scripts
  are already absorbed into their playbooks, which target them by name —
  both wait only on their live check-mode passes; voltaire is still
  owned by hand. **No playbook targets this group as a group.**
  Migrating a host means moving it between the two groups by hand,
  after its check-mode pass comes back clean.
- `excluded` — kangaroo. QTS ships no Python interpreter at all (no
  `python3`, no `/opt/bin/python3`, only the MalwareRemover and
  Container Station QPKGs), so it can never be an Ansible target.
  `kangaroo_bootstrap` is permanent, not interim.
- `docker_hosts`, `komodo_periphery_hosts`, `devboxes` — role groups.
  `site.yml` gates each role on membership.

## Running it

Ansible is a control-node dependency only; nothing is installed on
targets beyond a Python interpreter, which Fedora already has. It lives
in the repo's `.venv`.

```
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
disconnects. Like the script it replaced, the bootstrap play is only
truly exercised by the next rebuild.

`playbooks/numbat.yml` is the steady state — base, docker, numbat_edge,
sshd_pomerium_ca, komodo_periphery — reached through Pomerium like any
managed host, and the thing check-mode equivalence proves against the
live gateway.

## Adding a host

See [Hosts → Adding another host](hosts.html#adding-host) for the
end-to-end sequence including the Komodo-side resources.
