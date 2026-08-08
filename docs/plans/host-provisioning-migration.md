# Host bootstrap — target state and migration

Retire the bootstrap shell scripts into the Ansible layer and make host
bootstrap a three-layer, three-command story. The layer itself is built
and documented in [Host provisioning](../host-provisioning.md); this
plan carries the design for what has not moved yet, and the cleanup that
has to travel with it.

**Goal:** provisioning or rebuilding any host is exactly

1. `terraform apply` — cloud and edge resources, identities, PKI; every
   cross-host value it generates is published to 1Password.
2. `ansible-playbook` — all machine state, from first SSH to a Periphery
   that Core reports `Ok`. The host's bootstrap script is deleted, not
   kept as a second source of truth.
3. `chezmoi init --apply` — user state, probing capabilities rather than
   declaring them.

kangaroo is the sole permanent exception (QTS has no Python;
`kangaroo_bootstrap` stays). Komodo continues to own everything
containerized; a push still deploys stacks and never host state.

## Design rules

The simplicity target is **one producer, one channel, zero copies** for
every piece of cross-host state:

- **One producer.** Values Terraform generates (PKI, addresses, tokens)
  live in Terraform state and nowhere else. Values a host generates
  (Forgejo's host key, Periphery private keys) stay on the host that
  made them, with only the public half committed or documented.
- **One channel.** 1Password is the only distribution path for anything
  that crosses hosts. Terraform already publishes there in thirteen
  places; Ansible already reads there (`community.general.onepassword`
  in `komodo_periphery`); chezmoi reads there via `op-homelab`. No new
  mechanism on either end — the work is moving stragglers onto the
  existing wire.
- **Zero copies.** The repo carries no file whose content is derivable
  from Terraform state. `pomerium/keys/user-ca.pub` (and the `check`
  block that nags about its drift) is the one such file today; it goes.
  The narrow exception is a **root-of-trust literal a fresh machine
  needs before it can reach any channel** — the Forgejo host key in the
  dotfiles README, and now the Pomerium SSH host-key *fingerprint*
  there for human TOFU verification on non-homelab machines.
- **Terraform feeds, never drives.** Rejected: having `terraform apply`
  run playbooks. Provisioners are invisible to `plan` (breaking the
  from-anywhere contract), a failed playbook would taint and replace
  the resource it ran on, most of the fleet is not TF-created, and
  AGENTS.md already fixes the cadence: host state changes when a human
  runs a playbook. Terraform's job ends at publishing values; cloud-init
  templating TF's own values into a first boot is fine and stays.

## What does not change

- The push-to-deploy procedure, content hashes, Komodo's ownership of
  stacks, `komodo-sync`.
- `terraform/numbat/cloud-init.yaml.tftpl` — TF templating its own
  outputs at create time is the pattern working correctly.
- `kangaroo_bootstrap` (permanent) and `tailscale-recovery-bootstrap`
  (must run on kangaroo, so it stays ONE script; Ansible invokes it on
  systemd hosts rather than growing a parallel role).
- The chezmoi/Ansible boundary: root state vs user state.

## State-ownership ledger

| Value | Producer | Channel | Consumers after migration |
|---|---|---|---|
| Pomerium SSH user CA (public) | TF `tls_private_key.pomerium_ssh_user_ca` | 1P `Pomerium Secrets` (new field) | `sshd_pomerium_ca` role; cloud-init (TF-direct); kangaroo_bootstrap (op read on the bilby side) |
| Pomerium SSH host key (public) | TF `tls_private_key.pomerium_ssh_host` | 1P `Pomerium Secrets` (new field) | chezmoi `00-ssh-hostkeys` upsert; README fingerprint for TOFU |
| numbat application + relay IPv4 | TF (BinaryLane) | 1P (new fields beside the other numbat handoffs) | numbat host_vars → nft/dispatcher templates |
| numbat host SSH key | TF `tls_private_key.numbat_ssh_host` | 1P (public half) | numbat bootstrap play pins first contact |
| Rathole tokens, noise keys | TF `random_password` | 1P `Numbat Rathole` (existing) | relay `.env` renders via lookup |
| Periphery X25519 private keys | generated on bilby | `/opt/komodo/keys` on the control node only | `komodo_periphery` role (already) |
| Forgejo SSH host key | Forgejo container | committed literal in dotfiles (root of trust) | unchanged |

## Slices

Ordered by dependency. Slice 1 unblocks everything; 2–4 are then
independent of each other.

### 1. Move key distribution onto the channel

- Terraform: add plaintext public-half fields to the existing
  `Pomerium Secrets` item (`ssh_user_ca_pub`, `ssh_host_key_pub`) and
  publish numbat's two addresses beside the existing numbat handoffs.
  No new items, no new storage location — the item already holds both
  private halves.
- `sshd_pomerium_ca`: replace the `copy: src=pomerium/keys/user-ca.pub`
  with the 1P lookup the layer already uses.
- chezmoi `00-ssh-hostkeys`: derive the `ssh.pod.haus` host key via
  `op-homelab`, gated on the `op-homelab-ready` probe, and **upsert**
  (`ssh-keygen -R` first) so a rotation replaces rather than accumulates.
  Non-homelab machines (voltaire) get a documented fingerprint in the
  README and a human TOFU check, same stance as the Forgejo key.
  Rotation consequence: homelab machines self-heal on next apply;
  non-homelab machines fail loudly and are fixed by hand.
- Delete `pomerium/keys/user-ca.pub` and the `check` block once
  `numbat_bootstrap` (its last file consumer besides the role) is
  migrated in slice 3 — or switch that one `copy` line to an `op read`
  immediately and delete the file in this slice. Prefer the latter:
  the file's absence is what proves the channel is complete.
- ~~fractal `homelab = true`~~ mechanism shipped in dotfiles
  (`op-homelab-ready` probe); flipping the flag needs Nathan at fractal.

### 2. bilby into `provisioned`

The gate for everything bilby-hosted, and the first host where
check-mode equivalence is proven against a live, loaded machine.

Done so far: the repo side is complete. The docker role is bilby-safe
(`podhaus_docker_engine_managed`, templated `daemon.json` whose
false-render is byte-identical to bilby's live file, `attachable`
unspecified on dockernet, `podhaus_extra_networks` for the fenwick
nets); the two installers are absorbed into the `nfs_binds` and
`firewalld` roles (`bilby/host-systemd/` and `bilby/firewalld/`
deleted); `sshd_pomerium_ca` removes the legacy appended `sshd_config`
block; `playbooks/bilby.yml` + `host_vars/bilby.yml` exist
(`ansible_connection: local`); `komodo-start` is Komodo-only and
sudo-free.

Remaining — each a deliberate human act, in order:

- [x] Live equivalence pass (2026-08-03): `--check --diff` came back
  `ok=23 changed=5 failed=0`, every change an intended migration delta —
  the new `sshd_config.d` drop-in, removal of the legacy appended CA
  block (+ its reload handler), and two comment-only firewalld XML
  updates. Everything dangerous compared clean: `daemon.json`
  byte-identical, dockernet + fenwick nets untouched, sentinels/units
  `ok`. The `all_squash` wrinkle resolved itself: `file:`-asserted
  ownership on the `/mnt/jump/forgejo` trees compares stable (`ok`).
  Two fixes came out of the pass and are in the role:
  `ansible_python_interpreter: /usr/bin/python3` for the local
  connection, and `/var/lib/forgejo/config` at 0700 (Forgejo's runtime
  tightens it; asserting 0750 would flip-flop).
- [x] Real run (2026-08-04): `ok=28 changed=6 failed=0`, matching the
  check-mode preview exactly. Second run: `changed=0`. Postmortem spot
  checks all clean: `wait-for-qnap-nfs.service` enabled; `firewall-cmd
  --list-services` → `dhcpv6-client mdns music-assistant plex ssh`;
  sentinels present on pouch/jump/jump-forgejo; `sshd -T` trusts
  `pomerium-user-ca.pub`; dockernet/fenwick subnets unchanged. The
  tripwire task itself reported `ok` (bit already set, verified via its
  bind-mount check) — `lsattr` against the live mountpoint can't see it
  because NFS shadows the underlying inode, which is expected, not a
  failure.
- [x] Live-restore flip (2026-08-04, Nathan authorised it outside the
  04:00 window): pre-flight confirmed all 45 containers carry
  `unless-stopped`, real run `ok=8 changed=2` matching the check-mode
  preview, and afterwards `Live Restore Enabled: true` with the same 45
  containers back and the external chain green. Full
  `site.yml --limit bilby` re-run → `changed=0`. bilby is done.
- [x] Moved bilby from `pending_migration` to `provisioned` (2026-08-04).
  Decided: group-gated like `docker_hosts` — `site.yml` gained
  `komodo_core_host`/`nfs_binds`/`firewalld` roles behind new
  `komodo_core_hosts`/`nfs_binds_hosts`/`firewalld_hosts` groups, so a
  future host inherits bilby's roles by group membership alone, matching
  every other role in that file. The two Komodo Core directory tasks
  moved out of `bilby.yml`'s inline `tasks:` into a new `komodo_core_host`
  role for the same reason. `bilby.yml` stays as a single-host entry
  point (fractal.yml's precedent) but now just calls that role too.
  Proven equivalent: `ansible-playbook playbooks/site.yml --limit bilby`
  → `changed=0`.

### 3. numbat, as two plays

Done so far: `numbat_bootstrap` and `numbat/host/` are gone.
`playbooks/numbat-bootstrap.yml` (fresh VM, sequencing preserved as
play order) and `playbooks/numbat.yml` (steady state) own the host,
sharing the `numbat_edge` role; docs describe the resulting system
([host-provisioning.md](../host-provisioning.md),
[disaster-recovery](../disaster-recovery.html)).

Remaining:

- [x] Live equivalence pass + real run through Pomerium (2026-08-08):
  check-mode deltas audited (all intended — `sshd_pomerium_ca` drop-in,
  `daemon.json` byte-normalisation, base packages), real run `ok=43
  changed=10`, second run `changed=0`, Core reports the server Ok
  afterwards. The connection rides `ansible_user: nathan@numbat` (the
  Pomerium route selector — Ansible's ssh plugin emits `-o User` before
  `ssh_common_args`, so an `ssh_config` User rewrite can never win);
  OS-account work uses the new `podhaus_operator` var instead.
- [x] Moved numbat from `pending_migration` to `provisioned`; `site.yml`
  gained `numbat_edge` behind a new `edge_hosts` group, matching the
  group-gated pattern of every other role.
- [ ] The bootstrap play itself is only truly exercised by the next
  rebuild.

### 4. voltaire — a full homelab member

Decided: voltaire is an owned piece of the homelab, not a minimal SSH
target — the earlier "it's a work machine" carve-out is retired. Target
is the **fractal profile**: Ansible for machine state (base, devbox,
docker, sshd_pomerium_ca, komodo_periphery), Komodo for containers
(`relay/voltaire` origin, `logging/voltaire`, `autoheal/voltaire`), and
chezmoi with `homelab = true` — which the `op-homelab-ready` probe now
makes safe to answer truthfully on a machine where op is not signed in
yet.

Making it a full docker + Periphery host **deletes a planned role**:
its SSH origin becomes a Komodo-managed rathole *container* at
`172.18.0.1:22` (the bilby/fractal/kangaroo pattern), so no systemd
`rathole_ssh_origin` role is needed — by anyone, ever. Every host's
origin ends up managed the same one way.

- [x] Audit (2026-08-08, via the live Pomerium SSH path): Fedora 44
  Workstation, x86_64, 12 cores / 31 GiB, 475 GB LUKS root(+/home), TPM
  present and the chezmoi machine key already probes `hardware`. sshd
  already trusts the Pomerium user CA (`00-podhaus-pomerium-ca.conf`);
  passwordless sudo; Python 3.13; fish is the login shell; mise/node/op
  present; dotfiles current; `homelab = false` (flip is part of this
  slice). **Podman-only today** — docker absent. The coexistence risk is
  bounded: the one live container (`hybrid-sim-postgres-dev`, in-flight
  analysis work) runs `pasta` user-mode networking with a host-published
  port, which never traverses iptables FORWARD, so docker's FORWARD-DROP
  policy can't break it. Voltaire sits on a foreign LAN (192.168.0.x) —
  no home-LAN path; today's access is the `podhaus-pomerium-ssh-origin`
  systemd rathole (active, verified — it carried the audit) plus the
  legacy cloudflared tunnel (`ssh://localhost:22`, voltaire.pod.haus).
  `relay/numbat` already carries the `voltaire_ssh` server service and
  Pomerium the `ssh://voltaire` route — the origin swap is client-side
  only. **In-flight agent work to protect** (no reboot, no session
  teardown): a long-running autonomous claude session, several codex
  servers, an attached tmux session, and the postgres container.
- **One container engine, decided**: podman/docker coexistence is a
  bounded migration state only. Docker is the fleet contract; the end
  state is docker-only with the Ansible docker role asserting podman
  absent so it can't creep back. The live `hybrid-sim-postgres-dev`
  moves to docker (stop podman container → recreate on docker at the
  same published port, dump/restore if its data is volume-resident) —
  but podman *removal* is gated on the hybrid-haul spike wrapping (or
  on confirming none of its in-flight agents shell out to the podman
  CLI). Until that gate clears, coexistence is tolerated and the pasta
  finding above bounds the risk.
- Provision (order matters; the tunnel stays up as the fallback until
  the end): keypair on bilby + `komodo/keys/voltaire-periphery.pub` +
  `KOMODO_PERIPHERY_PUBLIC_KEYS` append; host_vars (`ansible_user:
  nathan@voltaire` — Pomerium route selector, numbat's pattern;
  `podhaus_operator: nathan`) + `playbooks/voltaire.yml` (base, devbox,
  docker, sshd_pomerium_ca, komodo_periphery) + role groups; servers/
  repos TOML (`podhaus-voltaire` linked repo); the three stacks
  (`relay/voltaire`, `logging/voltaire`, `autoheal/voltaire`). Verify
  the postgres container still answers after docker.service starts.
- Origin swap: stop `podhaus-pomerium-ssh-origin.service`, deploy
  the `relay/voltaire` container on the same `voltaire_ssh` token,
  verify `ssh voltaire.pod.haus` end to end through the container
  origin (the tunnel is the recovery path if the swap fails).
- **Tailscale recovery before tunnel teardown**: voltaire has no
  recovery-plane membership today — the tunnel is currently its only
  non-Pomerium path, so break-glass must exist before the tunnel dies.
  Enroll via `tailscale-recovery-bootstrap` (userspace, SSH-only,
  `tag:recovery`) + the TF recovery-plane resources, same as
  bilby/numbat/kangaroo; verify `voltaire-recovery` answers.
- Then **tear down the tunnel** (decided):
  `cloudflare_zero_trust_tunnel_cloudflared.voltaire`, the CNAME, and
  the host-side cloudflared service + `/etc/cloudflared`, plus the
  now-dead systemd origin unit + `/usr/local/libexec/podhaus-rathole`.
- Then `pomerium-ssh-origin-bootstrap` has one consumer left: kangaroo's
  ~20-line QTS `--ca-only` branch. Fold that into `kangaroo_bootstrap`
  (CA text supplied by `op read` on the bilby side) and delete the
  332-line generic script.

### 5. pinelake lands on Ansible

Forward guidance, superseding the pinelake plan's open item
("separate script vs parameterised `kangaroo_bootstrap`"): **neither —
a playbook.** pinelake is infrastructure and macOS has a Python;
`community.general.homebrew`, launchd via `template:` + `command:`,
Colima sizing per the pinelake host-bootstrap stream, and the same
`komodo_periphery` role with a host_var'd docker socket. The pinelake
plan's host-bootstrap page should be updated to point here when that
work starts.

## Verification

- Per host: check-mode-to-zero before joining `provisioned`; second
  real run `changed=0`; a config-level signal per subsystem (Komodo
  `state=Ok`, rathole control channels, `sshd -T`, Gatus staying green)
  — never "container healthy".
- Slice 1 end state is provable by absence: `git grep user-ca.pub`
  returns only cloud-init and docs.
- The two postmortem-hardened bilby subsystems (`nfs_binds`,
  firewalld) get their spot checks run after the first real apply, not
  assumed from `changed=0`.

## Decisions (settled 2026-08-03)

1. **bilby adopts `live-restore`**, flipped in a scheduled 04:00-window
   restart, not by handler.
2. **voltaire tunnel is torn down** once Pomerium SSH is verified, and
   voltaire becomes a full homelab member (fractal profile) rather than
   a minimal SSH target.
3. **numbat addresses ride 1P**, not DNS derivation — a DNS lookup
   would derive the value from one of its own consumers (reverse
   dependency, proxied-flip footgun, cache lag during the exact rebuild
   window the play exists for).

## Deliberately not in scope

- **kangaroo.** No Python, ever. Not a deferral.
- **The MacBook.** chezmoi only — personal device, not infrastructure.
- **Wiring Ansible into push-to-deploy.** Host state changes when a
  human runs a playbook. A push must not reconfigure a machine.
- **Engine swaps** (bilby moby→docker-ce) and **FDE** — the latter is
  tracked in [secret-architecture.md](secret-architecture.md).

## Open questions

- Should uncommitted work in fractal's `~/repos` be backed up? Nothing
  else on the host needs it, but a dev machine accumulates
  work-in-progress that exists nowhere else. Needs a decision, not a
  default.
- Should `pending_migration` hosts get a read-only `--check` drift pass
  while they wait? Only worth it if the remaining migrations spread out.
