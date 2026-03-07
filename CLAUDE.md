# PodHaus

Docker container infrastructure for home servers deployed to podhaus (pod.haus) and pinelake (pinelake.haus).

## Architecture

- **Komodo Core** manages all services as Docker Compose stacks
- Each service has a top-level directory with `compose.yaml` and `stack.toml` (Komodo metadata)
- Repo root is mounted into both Core (ResourceSync) and Periphery (compose files)
- Secrets flow from 1Password → komodo-op → Komodo Variables → `[[VARIABLE]]` interpolation in stack environments
- Non-secret variables defined in `komodo/sync/variables.toml`
- Volumes are declared in compose files without `external: true` — Docker Compose creates them on first deploy
- `komodo-start` bootstraps everything: starts Core, seeds variables, creates ResourceSync, triggers sync

## Networking

- `dockernet`: bridge network at 172.18.0.0/16 for cross-stack communication
- Containers reference each other by container name (Docker DNS), never by static IP
- Static IPs are only for LAN devices (e.g. UniFi gateway at 10.0.0.1) or host-network services
- Services needing device access use `network_mode: host` (e.g. home-assistant)
- Cloudflare Tunnel routes `*.pod.haus` subdomains directly to backends (no nginx)

## Key files

- `komodo/ferretdb.compose.yaml` — Komodo Core infrastructure (postgres, ferretdb, core, periphery)
- `komodo/compose.env` — Komodo config with `op://` secret references
- `<name>/compose.yaml` — Docker Compose file for each service stack
- `<name>/stack.toml` — Komodo stack metadata (server assignment, environment variables)
- `komodo/sync/variables.toml` — non-secret variables (MEDIA_DIR, TZ)
- `komodo/sync/servers.toml` — server definitions
- `komodo-start` — bootstrap script (starts Core, seeds variables, runs sync)
- `komodo-sync` — trigger ResourceSync without full restart
- `komodo-stop` — shut down Komodo Core
- `komodo-status` — show Komodo container status
- `komodo-upgrade` — pull latest images and restart
- `dns/dnsconfig.js` — DNSControl zone declarations (Cloudflare + UniFi)
- `dns/creds.json` — DNSControl provider credentials (env var refs, no secrets)
- `dns-preview` — DNSControl dry-run script
- `dns-push` — DNSControl apply script

## When adding a new service

1. Create `<name>/compose.yaml` with the Docker Compose definition
2. Create `<name>/stack.toml` with `files_on_host = true` and `run_directory = "/etc/komodo/repo/<name>"`
3. Add any needed secrets to 1Password Homelab vault (komodo-op syncs them automatically)
4. Add any non-secret variables to `komodo/sync/variables.toml`
5. Run `./komodo-sync` to deploy
6. Add a Cloudflare Tunnel ingress rule in `cloudflare-tunnel/compose.yaml` if the service needs a subdomain
