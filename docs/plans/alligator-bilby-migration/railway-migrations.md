# Railway migrations: Doggos and Yiayia

Two services still run on Railway. Their DNS records in
`terraform/dns_pod_haus.tf` point at Railway, and no `doggos/` or `yiayia/`
stack exists in this repo.

## Current services

### Yiayia Board

- Private source repo: `LogicWolfe/yiayia-board`
- Runtime: FastAPI, a static frontend, and Playwright
- State: `/data/yiayia_board.db` on a Railway volume
- Public hostname: `yiayia.pod.haus`
- Secret to move into 1Password: application `SECRET_KEY`

### Doggos

- Private source repo: `LogicWolfe/indigo-web-server`
- Runtime: static site with FTP and SSH upload paths for Blocs
- State: none outside the source tree
- Public hostname: `doggos.indigo.pod.haus`
- Secrets to move into 1Password: FTP password and SSH public key

The Railway account token is at
`op://Homelab/railway-api-token/credential`. The CLI expects
`RAILWAY_API_TOKEN`, `RAILWAY_PROJECT_ID`, and `RAILWAY_ENVIRONMENT_ID`.

## Open decisions

1. Obtain access to both private GitHub repos and build from source. If Doggos
   access remains unavailable, mirroring the public static site is an acceptable
   fallback. Yiayia should be rebuilt from source.
2. Decide whether Doggos remains public at `doggos.indigo.pod.haus` or moves to
   a single-label `*.pod.haus` hostname. Pomerium routes are explicit, so either
   hostname works if Doggos becomes protected; keeping the current public name
   avoids a needless URL change.
3. Confirm whether Doggos still needs its FTP and SSH upload paths. Remove them
   from the new deployment if Blocs now publishes through Git instead.

## Implementation

1. Create `doggos/` and `yiayia/` stacks following
   [Stack conventions](/stack-conventions.html). Store state on bilby's local
   NVMe and add a Backrest plan for Yiayia's SQLite database.
2. Add the required Homelab items in 1Password and wire their Komodo variables
   through each stack's `stack.toml`.
3. Stop writes to Yiayia, copy `/data/yiayia_board.db` from Railway, restore it
   into the local state path, and deploy both stacks through the normal push
   procedure.
4. Move ingress and DNS in the consolidated Terraform root:
   - For a protected service, add its DNS record to
     `terraform/services_pod_haus.tf`, its policy route to
     `pomerium/config.yaml`, and its private origin route to `caddy/Caddyfile`.
   - For a public Doggos site, publish a proxied record to Numbat's relay
     address and add it to Caddy's public-only listener with the standard
     Authenticated Origin Pull contract.
   - Do not add Cloudflare Tunnel or Access resources; Podhaus browser ingress
     is owned by Numbat, Pomerium, and Caddy.
5. Run `terraform plan` and `terraform apply` from `terraform/`, then verify the
   public hostnames serve from bilby.
6. Update Gatus. Yiayia already has frontend and device checks; add Doggos and
   switch any backend-specific assertions.
7. Keep Railway available for 72 hours as rollback, then remove both projects.

## Verification

- Yiayia serves the existing board and retains all SQLite state.
- Yiayia's Playwright-backed device check passes from the local container.
- Doggos serves the expected site and its chosen publish path works.
- DNS resolves through the intended Cloudflare path and `terraform plan` is
  clean after apply.
- Gatus is green before the Railway projects are removed.
