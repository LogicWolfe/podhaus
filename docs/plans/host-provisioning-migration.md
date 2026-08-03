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

- [ ] Live equivalence pass:
  `ansible-playbook playbooks/bilby.yml --check --diff` to zero.
  Expected wrinkle to verify here: whether `file:`-asserted ownership
  on the QNAP shares (`/mnt/jump/forgejo` trees) reports stable under
  `all_squash`, or shows a perpetual diff the role must adapt to.
- [ ] Real run; second run `changed=0`; then the postmortem-derived
  spot checks (`systemctl cat wait-for-qnap-nfs`, `firewall-cmd
  --list-services`, sentinel files, `sshd -T | grep
  trustedusercakeys`, dockernet/fenwick subnets unchanged).
- [ ] The 04:00-window live-restore flip: set
  `podhaus_docker_live_restore: true` in `host_vars/bilby.yml`, run
  the play in the window, take the one unprotected daemon restart,
  then confirm a subsequent daemon restart leaves containers running.
- [ ] Move bilby from `pending_migration` to `provisioned`, and decide
  how `site.yml` covers the bilby-only roles (`nfs_binds`,
  `firewalld`) — group-gated like `docker_hosts`, or `bilby.yml`
  stays the entry point.

### 3. numbat, as two plays

Done so far: `numbat_bootstrap` and `numbat/host/` are gone.
`playbooks/numbat-bootstrap.yml` (fresh VM, sequencing preserved as
play order) and `playbooks/numbat.yml` (steady state) own the host,
sharing the `numbat_edge` role; docs describe the resulting system
([host-provisioning.md](../host-provisioning.md),
[disaster-recovery](../disaster-recovery.html)).

Remaining:

- [ ] Run the live check-mode equivalence pass through Pomerium:
  `ansible-playbook playbooks/numbat.yml --check --diff` to zero.
  Gated on slice 2's generalised docker role being merged — numbat sets
  `podhaus_docker_engine_managed`/`podhaus_docker_live_restore`, needs
  the distro-derived `linux/rhel` repo URL, and takes a one-time
  byte-normalising `daemon.json` restart (safe: live-restore is already
  active there). Expected first-run deltas beyond that: the
  `sshd_pomerium_ca` drop-in (new file, same trust) and possibly
  dockernet options if the script-era `docker network create` picked a
  different subnet — verify before letting the role touch it.
- [ ] Then move numbat from `pending_migration` to `provisioned`
  (`site.yml` covers it via the role groups it already joined).
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

- **Audit first** (via the tunnel, while it exists): specs, sshd state,
  the TPM machine key, and docker-ce coexistence with the existing
  podman install (expected fine on Fedora; verify before committing).
- Provision: keypair on bilby, `komodo/keys/voltaire-periphery.pub`,
  servers/repos TOML entries, the three stacks, the playbook run.
- Verify `ssh voltaire.pod.haus` through Pomerium end to end, then
  **tear down the tunnel** (decided):
  `cloudflare_zero_trust_tunnel_cloudflared.voltaire`, the CNAME, and
  the host-side cloudflared service + `/etc/cloudflared`.
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
