# Host provisioning migration

Move the remaining fleet from bootstrap shell scripts onto the Ansible
layer. The layer itself is built and documented in
[Host provisioning](../host-provisioning.md) — this plan tracks only
what has not moved yet.

**Goal:** every host that can run Python is provisioned by
`ansible/`, and its bootstrap script is deleted rather than left as a
second source of truth.

## Done so far

- The `ansible/` layer exists: inventory, group/host vars, and the
  `base`, `wsl`, `docker`, `devbox`, `komodo_periphery`, and
  `sshd_pomerium_ca` roles.
- **fractal** is fully provisioned by it, from bare WSL to a Periphery
  that Core reports `Ok`. It never had a bootstrap script.
- The chezmoi/Ansible boundary is fixed at root state vs user state and
  verified safe to enforce: chezmoi's darwin branch is already sudo-free.
- **kangaroo is permanently excluded** — verified to have no Python
  interpreter of any kind under QTS.

## Remaining

Each host below is migrated the same way, and the order between them
does not matter. What does matter is the order *within* a host:

1. Write or extend roles until `--check --diff` against the live host
   reports **no changes** — that is the equivalence proof that Ansible
   would reproduce what the script built.
2. Move the host from `pending_migration` to `provisioned` in
   `inventory/hosts.yml`.
3. Run for real, then run again and confirm `changed=0`.
4. Delete the bootstrap script and its references in `AGENTS.md` and
   `docs/`.

### numbat (`numbat_bootstrap`)

The hardest, so worth doing early — it is the one that will shape the
roles. Its bootstrap has genuine ordering constraints: the relay must
be up before Periphery, the final nftables ruleset lands after that,
and port 2222 closes last. That sequence is a property of the *host
being remote and self-firewalling*, not of the script, so it has to
survive the move. Needs new roles for nftables and the recovery-path
Tailscale daemon.

### bilby (`bilby/host-systemd/install.sh`, `bilby/host-sshd/install.sh`)

bilby is the control node, so it provisions itself over the local
connection. Its installer already stages firewalld from
`bilby/firewalld/` declaratively — that model is close to Ansible's and
should map onto a role cleanly. The `wait-for-qnap-nfs.service` oneshot,
the automount `StartLimit*` drop-ins, and the `chattr +i` tripwires and
share sentinels all come across as a single `nfs_binds` role; they are
load-bearing (see the 2026-05-30 postmortem) and must keep working
identically.

The `sshd_pomerium_ca` role already replaces the CA half of
`bilby/host-sshd/install.sh`.

### voltaire

Specs and current state unconfirmed — `voltaire.pod.haus` failed host-key
verification through Pomerium and was not chased. **Establish access
first**; the migration can't be scoped until then. It has a TPM-resident
machine key, so its chezmoi half differs from fractal's.

## Deliberately not in scope

- **kangaroo.** No Python, ever. Not a deferral.
- **The MacBook.** chezmoi only. The discriminator is personal device vs
  infrastructure, not OS — pinelake is a Mac and *is* infrastructure, so
  it will take Ansible when it lands.
- **Wiring Ansible into push-to-deploy.** Host state should change when
  a human runs a playbook. A push must not reconfigure a machine.

## Open questions

- **Should uncommitted work in fractal's `~/repos` be backed up?** Nothing
  else on the host needs it — see the fractal section in
  [Hosts](../hosts.html#fractal) — but a dev machine accumulates
  work-in-progress that exists nowhere else, which is exactly the
  category backups are for. Needs a decision, not a default.
- Should `pending_migration` hosts eventually get a read-only
  `--check`-in-CI pass, so drift between a script and its future role is
  visible before the migration rather than during it? Cheap, but only
  worth it if migrations are going to be spread out.
