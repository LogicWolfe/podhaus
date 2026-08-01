# podhaus

Docker infrastructure for three managed hosts. Compose stacks live in this
repo, Komodo deploys them, 1Password supplies secrets, and Terraform owns the
external infrastructure.

- **bilby:** Apple M1 Mac mini running Fedora Asahi Linux. It hosts Komodo Core
  and the primary services.
- **kangaroo:** QNAP NAS running QTS and Container Station. It hosts Syncthing,
  Backrest, Autoheal, Alloy, and Pouch MinIO.
- **kookaburra:** DigitalOcean Fedora droplet in Sydney. It is the stateless
  public relay for storage and Forgejo, with management traffic over Tailscale.

**pinelake** is a planned fourth host for the second household.

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

Bootstrap the remote hosts from bilby:

```sh
./kangaroo_bootstrap
./kookaburra_bootstrap
```

## Terraform

`terraform/` is the single Terraform root for Cloudflare, UniFi, GitHub,
DigitalOcean, Tailscale, MinIO, and Pocket ID. Run stock Terraform from that
directory. Credentials come from the chezmoi-rendered, repository-scoped shell
environment.

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
| `cloudflare-tunnel/` | Bilby's remotely configured Cloudflare connector |
| `caddy/`, `relay/` | Public TLS and raw relay path through Kookaburra |
| `tailscale/` | Bilby and Kookaburra management-plane nodes |
| `backup/`, `autoheal/`, `logging/` | Multi-host shared services |
| `clickstack/`, `gatus/` | Observability, health checks, and alerting |
| `bilby/`, `kangaroo/`, `kookaburra/` | Host bootstrap and host-level configuration |
| `docs/` | Current-state documentation and live plans |
| `<service>/compose.yaml` | A single-host service stack |
