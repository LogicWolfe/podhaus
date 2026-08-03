# podhaus

Docker infrastructure for four managed hosts. Compose stacks live in this
repo, Komodo deploys them, 1Password supplies secrets, and Terraform owns the
external infrastructure.

- **bilby:** Apple M1 Mac mini running Fedora Asahi Linux. It hosts Komodo Core
  and the primary services.
- **kangaroo:** QNAP NAS running QTS and Container Station. It hosts Syncthing,
  Backrest, Autoheal, Alloy, and Pouch MinIO.
- **numbat:** BinaryLane Rocky Linux VM in Perth. It is the public Pomerium and
  rathole gateway.
- **fractal:** Fedora under WSL2. It is an outbound-only remote development and
  podhaus service host.

**pinelake** is a planned host for the second household.

## Documentation

The live documentation is at <https://docs.pod.haus>. Start with:

1. [Architecture](docs/architecture.html)
2. [Hosts](docs/hosts.html)
3. [Komodo](docs/komodo.html)
4. [Stack conventions](docs/stack-conventions.html)

`AGENTS.md` is the canonical instruction file for agents working in this repo.

## Day-to-day operation

On bilby:

```sh
./komodo-start
./komodo-sync
./komodo-status
./komodo-upgrade
./komodo-stop
```

`komodo-start` is the bootstrap path. Normal deployments are commit and push.
The GitHub webhook runs `podhaus-push-deploy`, which reconciles definitions,
stamps content hashes, recreates stacks whose committed content changed,
deploys compose changes and new stacks, then restarts Ofelia so it re-reads
job labels.

Use `./komodo-sync` for local iteration without a push and after editing
`komodo/sync/procedures.toml`.

Python repository tools use the current stable Python and Pipenv releases from
`mise.toml`. Install the unpinned development dependencies once per clone:

```sh
mise install
mise upgrade --local
mise exec -- pipenv install --dev --python "$(mise which python)"
```

The pre-commit hook runs the linters through that environment. No lock file is
kept. Running those commands again upgrades mise's rolling `latest` aliases;
use `mise exec -- pipenv remove` first when Python itself has changed.

Bootstrap the remote hosts from bilby:

```sh
./kangaroo_bootstrap
./numbat_bootstrap
```

## Terraform

`terraform/` is the single Terraform root for BinaryLane, Cloudflare, UniFi,
GitHub, Tailscale, MinIO, and Pocket ID. Run stock Terraform from that
directory. Credentials come from the chezmoi-installed, repository-scoped shell
hook, which runs `op inject` when the shell enters this repository.

```sh
cd terraform
terraform plan
terraform apply
```

State lives in MinIO at `s3://terraform-state/podhaus.tfstate` through
`https://storage.pod.haus`. There is no Terraform wrapper and DNSControl has
been retired.

## Repository map

| Path | Purpose |
|---|---|
| `komodo/` | Core infrastructure, ResourceSync definitions, procedures, and actions |
| `terraform/` | Consolidated external infrastructure root |
| `onepassword/` | 1Password Connect and `komodo-op` |
| `pomerium/`, `caddy/`, `relay/` | Authenticated and raw ingress through Numbat |
| `tailscale-recovery-bootstrap` | SSH-only host recovery plane |
| `backup/`, `autoheal/`, `logging/` | Multi-host shared services |
| `clickstack/`, `gatus/` | Observability, health checks, and alerting |
| `bilby/`, `kangaroo/`, `numbat/`, `fractal/` | Host bootstrap and host-level configuration |
| `docs/` | Current-state documentation and live plans |
| `<service>/compose.yaml` | A single-host service stack |
