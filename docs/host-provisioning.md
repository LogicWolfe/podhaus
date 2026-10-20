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

The split covers the hosts Ansible provisions: homelab and remote machines of
any operating system, from the Linux fleet to numbat and the macOS appliance
pinelake. Nathan's personal laptop stands outside it. Chezmoi owns that machine
whole and Ansible never runs on it; its only root state, Remote Login and
sshd's key-only policy, is set once by hand when the laptop is set up and
never changes after. [MacBook setup](macbook-setup.md) lists every manual step
and dependency the laptop has.

Pinelake has one platform-forced exception: OrbStack stores its engine state in
`baxter`'s home directory and runs as that user. The `pinelake_macos` role owns
its CLI configuration and invokes OrbStack as `baxter`; automatic login creates
the Aqua session and OrbStack's supported login item starts the engine. Chezmoi
still does not participate. Ownership follows the infrastructure function where
macOS offers no system-wide container runtime.

A host can take both. fractal does — it is a podhaus host *and* Nathan's
development machine, so Ansible gives it Docker and Periphery while
chezmoi gives it fish and dotfiles. Neither layer knows about the other,
and `playbooks/fractal.yml` deliberately does **not** invoke chezmoi:
that would put user state under root's control and dissolve the boundary
the layer exists to draw.

## Shared configuration and generated state

Authored, non-secret LAN addresses live in `config/lan-addresses.json` and
travel through Git. Terraform, Ansible and bootstrap commands read that file
directly. `tools/render-lan-addresses.py` generates the committed Komodo
variable declarations; the pre-commit check rejects drift from the source.

Generated infrastructure state and credentials follow these rules:

- **One producer.** Values Terraform generates (keys, allocated public
  addresses, tokens) live in Terraform state. Values a host generates
  (Forgejo's host key, Periphery private keys) stay on that host, with only
  the public half committed or documented.
- **One channel.** Terraform publishes generated handoffs through 1Password.
  Ansible reads them on the control node, so targets need no `op` auth;
  chezmoi and operator commands use `op-vault` with the selected machine
  service account.
- **No copied state.** The repo carries no file derived from Terraform state,
  except a root-of-trust literal needed before reaching a distribution
  channel: the Forgejo host key and Pomerium SSH host-key fingerprint in
  the dotfiles README.
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
| Home-LAN addresses | `config/lan-addresses.json` | Git; generated Komodo variables | Terraform, Ansible, bootstrap commands and service stacks |
| Pomerium SSH user CA (public) | TF `tls_private_key.pomerium_ssh_user_ca` | 1P `Pomerium Secrets` | `sshd_pomerium_ca` role; numbat cloud-init (TF-direct); `kangaroo_bootstrap` (op read on the bilby side) |
| Pomerium SSH host key (public) | TF `tls_private_key.pomerium_ssh_host` | 1P `Pomerium Secrets` | chezmoi `00-ssh-hostkeys` upsert; README fingerprint for TOFU |
| numbat application + relay IPv4 | TF (BinaryLane) | 1P numbat handoffs | numbat host_vars → nft/dispatcher templates |
| numbat host SSH key | TF `tls_private_key.numbat_ssh_host` | 1P (public half) | numbat bootstrap play pins first contact |
| Relay CA, tunnel server and per-client certificates | TF `tls_*` in `terraform/tunnel.tf` | 1P `Numbat Tunnel` | tunnel stacks via Komodo variables; the numbat bootstrap play renders the server's `.env` via lookup |
| Per-host log-shipping mTLS certs | TF `voltaire_log_client` etc. | 1P `Log Ingest PKI` | logging stacks via Komodo variables |
| Periphery X25519 private keys | generated on bandicoot | `/opt/komodo/keys` on the control node only | `komodo_periphery` role |
| Forgejo SSH host key | Forgejo container | committed literal in dotfiles (root of trust) | chezmoi `00-ssh-hostkeys` |

## Which hosts Ansible manages

**fractal**, **bilby**, **numbat**, **voltaire**, **bandicoot**, **quokka**, and **pinelake** — the `provisioned`
group, which is what `site.yml` targets. How each is reached is a
per-host fact in `host_vars/`: bandicoot is the control node and runs
against itself (`ansible_connection: local`); bilby is direct on the
home LAN via `bilby.pod.haus`; Quokka is direct via `quokka.pod.haus`
at its USB Ethernet reservation `10.0.0.199`; fractal is direct on the home LAN too
(`10.0.0.70`, the address its WSL guest shares with the Windows host
under mirrored networking); numbat and
voltaire have no inbound path of their own and route through Pomerium,
carrying `nathan@numbat` / `nathan@voltaire` as `ansible_user` — that is
a Pomerium *route selector*, not an OS account, which is why
OS-account work uses the separate `podhaus_operator` var. Pinelake is a
dedicated macOS appliance reached through its outbound Numbat/Pomerium SSH
route. Its `pinelake_macos` role is separate from every Linux role.

**kangaroo is not an Ansible target and never will be** — QTS ships no
Python interpreter, so `kangaroo_bootstrap` is its permanent supported
path. Nathan's MacBook is not a target either: chezmoi owns the whole
laptop. It stays in inventory as a member of `remote_dev_machines`, so the
`authorized_keys` role grants its machine key on the Linux hosts, and in no
group a play targets.

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
    bandicoot.yml          single-host entry point (+ Komodo host dirs)
    bilby.yml              single-host entry point (+ Komodo Periphery)
    numbat.yml             single-host entry point (steady state)
    numbat-bootstrap.yml   fresh-VM bring-up, sequencing preserved as play order
    pinelake.yml           macOS appliance and OrbStack entry point
  roles/
    base/                  timezone, baseline packages, dirs, laptop power policy
    disk_tmp/              Root-filesystem /tmp policy, activated at host restart
    wsl/                   /etc/wsl.conf, hostname, no guest NTP daemon (Windows owns the clock)
    docker/                engine (where managed), daemon.json, host networks
    devbox/                the root-requiring half of a developer machine
    docs_sources/          Read-only repository source slots for docs-server
    gnome_on_demand/       GDM follows the shared lid/display policy (bandicoot, quokka)
    komodo_periphery/      keys, compose, and a wait-for-Ok gate
    sshd_pomerium_ca/      trust Pomerium's SSH user CA
    sshd_liveness/         drop SSH clients that stopped answering (dev hosts)
    storage_binds/         Late-arriving-volume hardening (bilby, fractal)
    firewalld/             declarative zone + service XML (bilby, bandicoot)
    komodo_core_host/      Komodo Core's host directories (bandicoot)
    numbat_edge/           numbat's nftables ruleset, relay-IP dispatcher, loopback sshd
    pinelake_macos/        macOS power, OrbStack and Plex safety gates
```

On development hosts with SELinux enabled, the `devbox` role labels TCP port
18339 as `ssh_port_t`. This lets SSH bind the reverse tunnel that connects the
remote clipboard tools to the Mac's cc-clip daemon. The listener remains on
loopback; the port is not opened in the firewall.

### Inventory groups

Hosts are grouped twice: by **whether Ansible manages them**, and by
**role**.

- `provisioned` — every Ansible-owned host. `site.yml` targets this group and
  nothing else, gating each
  role (including narrowly-scoped ones like `storage_binds`, `firewalld`, and
  `numbat_edge`) on the matching role group rather than on hostname, so a
  new host inherits the right roles from group membership alone.
- `excluded` — kangaroo. QTS ships no Python interpreter at all (no
  `python3`, no `/opt/bin/python3`, only the MalwareRemover and
  Container Station QPKGs), so it can never be an Ansible target.
  `kangaroo_bootstrap` is permanent, not interim. It is listed here
  rather than omitted so the inventory shows the whole fleet, with
  `ansible_host: unreachable.invalid` so a stray `--limit` can't dial it.
- `linux_hosts` and `macos_appliance_hosts` separate operating-system role
  families. Linux-only base, account, and sshd roles never run on Darwin.
- `docs_hosts` — Bilby, Fractal, Voltaire, Bandicoot, and Quokka. Each declares the aggregate
  repository directory and canonical chezmoi checkout that `docs_sources`
  exposes through stable root-owned slots.
- `docker_hosts`, `komodo_periphery_hosts`, `devboxes`, `edge_hosts`,
  `komodo_core_hosts`, `storage_binds_hosts`, `firewalld_hosts`, `disk_tmp_hosts`,
  `gnome_on_demand_hosts` — role
  groups. `site.yml` gates each role on membership.

## Running it

Ansible is a control-node dependency only; nothing is installed on
targets beyond a Python interpreter, which Fedora already has. It lives
in the repo's `.venv`.

```sh
cd ansible
op-vault dev -- ansible-playbook playbooks/fractal.yml --check --diff
op-vault dev -- ansible-playbook playbooks/fractal.yml
```

Authentication uses the caller's machine-key agent. `group_vars/all.yml`
passes `IdentityAgent` through from `$SSH_AUTH_SOCK`, so the same machine key
that lets the control node `ssh` to a host lets Ansible reach it. Personal
1Password authentication is not part of this path, and no private key material
is configured in Ansible.

Ansible lookups that need 1Password run from a Podhaus operator under the
machine's `dev` service account. Keeping every playbook inside the same
explicit boundary avoids a second invocation pattern for plays that do not
currently read a secret.

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
per subsystem (Komodo reporting `state=Ok`, tunnel clients
connected to the `numbat-tunnel` server, `sshd -T`), never "the container is healthy": a container
being up proves it started, not that it is doing its job.

A host gaining `earlyoom` or the Docker GPU switch for the first time cannot
be dry-run whole. A plain `--check` stops at the earlyoom service task, because
the unit does not exist until the package is really installed, and at the
toolkit install, because the repository file does not exist yet. Read that
first dry run with
`ansible-playbook playbooks/fractal.yml --check --diff --skip-tags earlyoom,docker-packages`,
which still shows the repository file and the daemon configuration, then apply.

## Roles worth knowing about

**`disk_tmp`** configures Bilby, Bandicoot, Voltaire, Fractal, and Quokka to keep `/tmp`
on their root filesystem by masking `tmp.mount`. Bilby, Bandicoot, Voltaire, and Quokka
use their local root disk; Fractal uses its WSL root virtual disk. Temporary files share the root
filesystem's free space and retain the distribution's temporary-file cleanup
policy. Apply with `op-vault dev -- ansible-playbook playbooks/site.yml
--tags disk-tmp --limit bilby,bandicoot,voltaire,fractal,quokka` from `ansible/` on Bandicoot,
after reviewing the same command with `--check --diff`.

The role leaves an active RAM mount in place because live processes hold files
and sockets there. A host restart activates the disk-backed directory. On
Fractal, `systemctl reboot` restarts the distribution while the shared WSL
kernel can remain running. An interactive login invokes `unlock-home` to restore
`/home`; it prompts for the passphrase only when the encrypted mapping is closed,
as after a full WSL shutdown. `systemctl show tmp.mount -p LoadState` verifies the persistent mask;
`findmnt -T /tmp` verifies the active backing filesystem. A masked unit with
`tmpfs` still mounted means the cutover needs a restart.

**`earlyoom`** runs Fedora's earlyoom on the development hosts Bilby,
Bandicoot, Fractal, Voltaire, and Quokka. When available memory and free swap both fall to 10%,
it signals the process with the highest out-of-memory score, before the host
stalls in swap. Chezmoi sets those scores for dev work, so the order is bash
commands (+900), then shells and agents (+600), then the tmux server (+300),
then services (0 or below). The avoid list is Fedora's, covering the user
manager, `dbus-broker`, and desktop sessions. systemd-oomd stays at Fedora's
default and acts only after a sustained stall. `journalctl -u earlyoom` shows
the thresholds at start-up and names each process it signals. Apply with
`--tags earlyoom`.

Fractal differs in two ways. Chezmoi does not set the dev-work scores there, so
earlyoom follows the kernel's own ranking, which in practice picks the process
using the most memory. And systemd-oomd runs there but monitors no cgroups,
because the WSL image lacks the `systemd-oomd-defaults` package; earlyoom is the
only early killer, and the kernel's own killer is what acts after it.

**`sshd_liveness`** makes sshd on the development hosts Bilby, Bandicoot,
Fractal, Voltaire, and Quokka probe each client every 15 seconds and drop one that
misses three probes in a row. Without it, a laptop that sleeps mid-session
leaves a dead connection that keeps its tmux client attached and its forwarded
ports bound for about fifteen minutes. That includes cc-clip's port 18339, so
the reconnected session cannot forward it and image paste stops working.
`sudo sshd -T | grep -i clientalive` shows the values. Apply with `--tags ssh`.

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

`podhaus_docker_nvidia_gpu` gives a host's containers the NVIDIA GPU; only
Fractal sets it, because the GPU belongs to Windows and is exposed to the WSL
guest. The role adds NVIDIA's own package repository, installs NVIDIA's
container toolkit from it, and renders the `nvidia` runtime into `daemon.json`,
so a GPU host's file differs from the others'. It refuses to run unless the
Windows-provided `/usr/lib/wsl/lib/nvidia-smi` is present, and it installs no
Linux NVIDIA driver. With the toolkit in place a Compose device request with
`driver: nvidia` reaches the GPU. Installing the toolkit restarts the Docker
daemon, which live-restore makes safe for running containers.
The toolkit puts `nvidia-smi` on the container's own path, so
`docker run --rm --gpus all --entrypoint nvidia-smi <image>` checks it with any
glibc-based image already on the host.

**`storage_binds`** carries the postmortem-hardened defences for any host
whose containers bind a volume that can arrive late. Each host declares its
volumes as `storage_binds_mounts` in `host_vars` — root, expected source,
and expected filesystem types — and everything else follows from that
declaration. bilby declares the two QNAP NFS exports; fractal declares
`/home`, the LUKS volume a human unlocks by hand, which is the same problem
wearing different clothes.

The role installs the recurring mount-aware recovery timer for eligible
`created`/`exited` containers, the `chattr +i` tripwire on each bare
mountpoint (a `script:` task — the non-recursive `mount --bind /` trick has
no Ansible primitive — with an honest `changed_when` on its output; it
sweeps empty Docker auto-create debris and fails loudly on anything holding
bytes), and a `.podhaus-share-mounted` sentinel on every volume root
(touched with `modification_time: preserve` so re-runs stay `changed=0`).

Three pieces are opt-in per host and stay empty where they do not apply: the
`StartLimit*=0` drop-ins on both the `.mount` and `.automount` half of each
fstab automount pair (bilby only — a hand-mounted volume has no unit pair to
un-cap), the managed directory trees (bilby's Forgejo ownership), and an
fstab pass number (bilby's `/boot/efi`, so systemd runs the ordinary
pre-mount FAT check).

**The recovery has no deadline, deliberately.** A volume that returns hours
later — a QNAP outage, or fractal's vault sitting locked until Nathan SSHes
in — takes exactly the same path as one that returns in seconds. The role
header carries the incident history; the postmortems are the full record.

**`docs_sources`** separates Docker's stable mount contract from user-owned
checkout availability. It creates `/opt/podhaus/docs-sources` as a shared host
mountpoint and one slot per `podhaus_docs_sources` entry. The recurring
`podhaus-docs-source-reconcile` service bind-mounts an available checkout
read-only over its slot; when the declared source or `required_path` is absent,
it withdraws the bind and reveals `.podhaus-source-unavailable`. Docs-server
mounts the slot root once with `rslave` propagation, so source transitions reach
the running container. Its `/health` becomes degraded while repositories from
other slots continue serving. The role owns only root state under `/opt`,
`/etc/podhaus`, and systemd; repository paths under `/home` remain user state.

Each entry in `/etc/podhaus/docs-sources.json` requires `name`, `type`,
`source` and `required_path`. The type is `directory` for a directory containing
repositories or `repository` for one checkout. Docs-server and Lumen consume
the same declaration. When its schema or reconciler changes, the role stops
the reconciliation timer and service before updating both files together.

**`firewalld`** stages the declarative zone + service XML from role
files — services before the zone, so the zone never references an
undefined service — validates with `firewall-cmd --check-config` on
every run, and reloads via handler only after validation passes. It
fails fast if firewalld is absent rather than skipping.

**`komodo_periphery`** ships the host's X25519 private key (`no_log`,
mode 0600) and Core's public key, renders `periphery.config.toml`,
pulls the current stable image before bringing the container up, and then
**polls Core's `ListServers` API until the Server reports
`Ok`**. That last gate is the point: a Periphery
container being healthy proves only that it started, not that Core
trusts its key or can reach it. The playbook fails if the handshake
doesn't complete.

The role's `podhaus_docker_home`, `podhaus_docker_cli`, and
`podhaus_docker_become` inputs preserve the same lifecycle on Pinelake: Compose
runs as `baxter` against the globally selected OrbStack engine, while Linux
hosts use their default root-owned engine. Runtime-specific Docker contexts do
not appear in deployed commands.

Periphery is deliberately *not* Komodo-managed on any outbound host —
Core reaches the host only through the connection Periphery makes, so a
Komodo-driven redeploy of it would sever the path it runs on. Ansible
owns it instead of a bootstrap script.

**`pinelake_macos`** configures no-sleep and restart-after-power-loss policy
while allowing the display to sleep after ten minutes. It installs current
OrbStack through Homebrew without a version pin, configures its supported
settings, and creates `dockernet`. Automatic login creates the `baxter` Aqua
session and OrbStack's own `app.start_at_login` setting owns runtime startup.
Ansible does not start or stop OrbStack or manage any of its privileged
helpers. The one launch daemon the role installs, `plex-advertise`, reconciles
Plex's advertised LAN address and touches nothing about the runtime. OrbStack exposes its engine through the sole
global `default` Docker context; deployed Compose calls do not name a runtime
context.

The role disables OrbStack's runtime-specific Docker context and unused
direct container-IP bridge, leaves LAN publication enabled, disables Kubernetes
and gives the Docker VM 8 CPUs and 8 GiB.
It also disables automatic full macOS upgrades so an unattended reboot cannot
bypass the Plex session gate, while background security data remains automatic.
macOS requires one
interactive removable-volume grant for OrbStack's signed application identity;
there is no supported Ansible or command-line grant without device management.
After that one provisioning consent, cold starts reuse the persisted grant.
The mount probe times out and fails the play if the grant is absent rather than
leaving a false-green runtime. Runtime updates are ordinary current-release
Homebrew maintenance, gated by the same two Plex session checks as every
operation that can restart its container.

Before a deployment can expose the TerraMaster to a container,
`pinelake-mount-guard` verifies
its APFS volume identifier, exact mount point, writable state, sentinel,
required directories, and a read-only container bind of the sentinel. Stack
pre-deploy gates bind and verify each required directory individually; services
never expose the whole media volume to the OrbStack file-sharing layer. The
Plex pre-deploy gate validates all four server identity fields and fails closed
on an unavailable session endpoint. Replacing a running server requires two
successful zero-session checks; Plex has no automatic recovery path that
bypasses that gate.

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
order, each constraint commented. The play runs **from bandicoot** (it
streams Periphery keys from `/opt/komodo/keys` and polls Core on
localhost), connects to the application IP on first-boot port 2222 with
the host key pinned from 1Password, stages the `numbat_edge` config
*without* loading the final ruleset (it would close 2222, the play's own
transport), punches only the relay ports into the live bootstrap table,
starts the `numbat-tunnel` server **before** Periphery (Periphery dials
`core-connect.pod.haus`, which resolves back through this host's own
relay address, where bilby's tunnel carries it to Core), enrolls the Tailscale recovery daemon, and closes 2222 last —
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

## Repository search

Lumen provides local semantic code search on Voltaire, Fractal, Bilby,
Bandicoot and Quokka. The Komodo stacks under `lumen/` own one Ollama embedding service per
host, its Jina code model, and the `lumen:local` tools image. The `lumen-models`
and `lumen-data` Docker volumes keep downloaded models and repository indexes
on that machine. Agent sessions share the index volume and embedding service;
each session runs its Lumen process in a separate container. macOS has no
Lumen deployment.

Ansible's `/etc/podhaus/docs-sources.json` is the repository declaration for
both docs-server and Lumen. The `docs_sources` role exposes its sources through
read-only mounts of `~/repos`, `~/.claude-worktrees` and the canonical chezmoi
checkout. Lumen discovers repositories beneath those sources and asks
Git for their linked worktrees, preserving original absolute paths inside its
containers so worktree metadata resolves to the same shared repository index.
Missing storage remains visible as an unavailable source; a sweep reports a
failure after processing the available repositories.

Chezmoi owns `~/.local/bin/lumen`, global Model Context Protocol (MCP) exposure
for Codex and both Claude profiles, and `worktree-setup-common <worktree-path>`.
Every participating repository calls that common command at the end of its
Linux `.worktree-setup`. New shared setup actions belong in the common helper;
repository scripts carry only the invocation. The helper starts background
indexing and prints its container name. Repeated calls reuse an active job for
the same worktree. Content hashing reuses existing embeddings, but a new
worktree still needs scanning and index membership updates.

The stack starts a full sweep on deployment. Ofelia starts the same
`lumen-sweep` container every ten minutes without overlapping scheduled runs;
the sweep indexes worktrees sequentially. This enrolls repositories whose setup
script has no common-helper invocation. Independently requested warm jobs can
run alongside the sweep. Stopping a sweep also stops its active index process.
See [Scheduling](scheduling.html) for the scheduler configuration.

A successful `lumen warm` invocation means a background job started or is
already running. Check the reported container's logs and exit status, then use the
MCP `index_status` tool and a relevant search. For foreground completion, run
`lumen index "$(git rev-parse --show-toplevel)"` from the intended worktree.
An existing MCP connection sees new worktrees beneath `~/repos` and
`~/.claude-worktrees` without reconnecting;
a worktree created outside those roots after connection startup needs a fresh
Lumen MCP connection, because warming cannot add mounts to an existing container.
Semantic results cover supported indexed content; exact and exhaustive checks
still require ordinary search tools.

There is no fixed memory reservation or CPU or memory quota. Cold indexing can
use most available CPU cores; CPU saturation alone is not treated as a failure
on these development hosts. Ollama unloads its model after five idle minutes,
while reclaimable file cache can remain charged to the container. Concurrent
sessions and indexing add variable memory use. Inspect `docker stats` and
container exit status when diagnosing resource pressure; do not infer a peak
from an idle sample or treat cached memory as a permanently loaded model.

The shared agent skills give the operational procedures:
[Lumen diagnostics](https://git.pod.haus/LogicWolfe/dotfiles/src/branch/main/dot_agents/skills/lumen-doctor/SKILL.md)
separates unavailable tooling, incomplete indexes and valid empty results;
[Lumen reindexing](https://git.pod.haus/LogicWolfe/dotfiles/src/branch/main/dot_agents/skills/lumen-reindex/SKILL.md)
warms a selected worktree and verifies completion. They are available to both
Claude and Codex. Docker access is required for the launcher and the embedding
service must be available locally for indexing and semantic queries.
