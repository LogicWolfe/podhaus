# PodHaus

Docker container infrastructure for home servers deployed to podhaus (pod.haus) and pinelake (pinelake.haus).

## Architecture

- **Komodo Core** manages all services as Docker Compose stacks
- Compose files live in `komodo/stacks/<name>/compose.yaml`, mounted into Periphery at `/etc/komodo/stacks/`
- Stack metadata and environment in `komodo/sync/podhaus-stacks.toml` (references compose files via `files_on_host = true`)
- Secrets flow from 1Password → komodo-op → Komodo Variables → `[[VARIABLE]]` interpolation in stack environments
- Non-secret variables defined in `komodo/sync/variables.toml`
- `komodo-start` bootstraps everything: starts Core, seeds variables, creates ResourceSync, triggers sync

## Networking

- `dockernet`: bridge network at 172.18.0.0/16 for cross-stack communication
- Services needing device access use `network_mode: host` (e.g. home-assistant)
- Cloudflare Tunnel routes `*.pod.haus` subdomains directly to backends (no nginx)

## Key files

- `komodo/ferretdb.compose.yaml` — Komodo Core infrastructure (postgres, ferretdb, core, periphery)
- `komodo/compose.env` — Komodo config with `op://` secret references
- `komodo/stacks/<name>/compose.yaml` — Docker Compose files for each stack
- `komodo/sync/podhaus-stacks.toml` — stack metadata, server assignment, environment variables
- `komodo/sync/variables.toml` — non-secret variables (MEDIA_DIR, TZ)
- `komodo/sync/servers.toml` — server definitions
- `komodo-start` — bootstrap script (starts Core, seeds variables, runs sync)
- `komodo-sync` — trigger ResourceSync without full restart
- `komodo-stop` — shut down Komodo Core
- `komodo-status` — show Komodo container status
- `komodo-upgrade` — pull latest images and restart

## When adding a new service

1. Create `komodo/stacks/<name>/compose.yaml` with the Docker Compose definition
2. Add a `[[stack]]` entry to `komodo/sync/podhaus-stacks.toml` with `files_on_host = true` and `run_directory = "/etc/komodo/stacks/<name>"`
3. Add any needed secrets to 1Password Homelab vault (komodo-op syncs them automatically)
4. Add any non-secret variables to `komodo/sync/variables.toml`
5. Run `./komodo-sync` to deploy
6. Add a Cloudflare Tunnel ingress rule in `komodo/stacks/cloudflare-tunnel/compose.yaml` if the service needs a subdomain
