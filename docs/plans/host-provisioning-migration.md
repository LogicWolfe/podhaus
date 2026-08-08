# Host bootstrap migration — remaining work

The migration itself is done for every current host: **fractal, bilby,
numbat, and voltaire** are in `provisioned` (each proven by a check-mode
equivalence pass, a real run, and a second run at `changed=0`), kangaroo
is permanently `excluded` (QTS has no Python — `kangaroo_bootstrap` is
the supported path, including Pomerium SSH CA trust), and the retired
bootstrap scripts (`numbat_bootstrap`, `pomerium-ssh-origin-bootstrap`,
`bilby/host-systemd`, `bilby/firewalld`) are deleted. The resulting
system is documented in [Host provisioning](../host-provisioning.md)
(including the one-producer / one-channel / zero-copies ledger) and
[Hosts](../hosts.html).

What's left:

## voltaire: podman package removal

Docker is voltaire's single container engine and its one podman
container (`hybrid-sim-postgres-dev`) has been dump/restored into
docker. Remaining, gated on the hybrid-haul spike work wrapping (or on
confirming none of its in-flight agents shell out to the podman CLI):

- [ ] Remove the stopped podman container + `hybrid_sim_postgres_data`
  podman volume (kept as the migration rollback until the gate clears).
- [ ] Remove the podman package, and have the Ansible docker role
  assert podman absent so it can't creep back.

## numbat: bootstrap play

- [ ] `playbooks/numbat-bootstrap.yml` is only truly exercised by the
  next fresh-VM rebuild. Nothing to do until then; noted so the first
  rebuild is treated as a validation run, not a routine one.

## pinelake lands on Ansible

Forward guidance, superseding the pinelake plan's open item ("separate
script vs parameterised `kangaroo_bootstrap`"): **neither — a
playbook.** pinelake is infrastructure and macOS has a Python;
`community.general.homebrew`, launchd via `template:` + `command:`,
Colima sizing per the pinelake host-bootstrap stream, and the same
`komodo_periphery` role with a host_var'd docker socket. The pinelake
plan's host-bootstrap page should be updated to point here when that
work starts.

Per-host verification bar (as used for every migrated host):
check-mode-to-zero before joining `provisioned`; second real run
`changed=0`; a config-level signal per subsystem (Komodo `state=Ok`,
rathole control channels, `sshd -T`) — never "container healthy".

## Deliberately not in scope

- **kangaroo.** No Python, ever. Not a deferral.
- **The MacBook.** chezmoi only — personal device, not infrastructure.
- **Wiring Ansible into push-to-deploy.** Host state changes when a
  human runs a playbook. A push must not reconfigure a machine.
- **Engine swaps** (bilby moby→docker-ce) and **FDE** — the latter is
  tracked in [secret-architecture.md](secret-architecture.md).

## Open questions

- Should uncommitted work in fractal's and voltaire's `~/repos` be
  backed up? Nothing else on those hosts needs it, but a dev machine
  accumulates work-in-progress that exists nowhere else. Needs a
  decision, not a default.
