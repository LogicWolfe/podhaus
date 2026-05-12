# cloudflare/

Terraform sources for every Cloudflare resource in podhaus (DNS, Zero
Trust Access, the cloudflared tunnel config) plus the UniFi
split-horizon A records and the GitHub webhook that drives Komodo
auto-deploy. State lives in MinIO at
`s3://terraform-state/cloudflare.tfstate`.

## Read this before operations

The provider docs are the authoritative source-of-truth for every
resource and data source. **Always read the resource page in the
registry before adding or modifying a resource here** — provider
schemas change between minor versions and our HCL needs to match.

| Provider | Source | Docs root |
|---|---|---|
| Cloudflare | `cloudflare/cloudflare` v5 | <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs> |
| UniFi | `ubiquiti-community/unifi` ~> 0.41 | <https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs> |
| GitHub | `integrations/github` ~> 6.0 | <https://registry.terraform.io/providers/integrations/github/latest/docs> |

Resources actively used in this root, with direct links:

- `cloudflare_dns_record` — <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/dns_record>
- `cloudflare_zero_trust_access_application` — <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_application>
- `cloudflare_zero_trust_access_policy` — <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_policy>
- `cloudflare_zero_trust_access_group` — <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_group>
- `cloudflare_zero_trust_access_service_token` — <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_service_token>
- `cloudflare_zero_trust_tunnel_cloudflared_config` — <https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config>
- `unifi_dns_record` — <https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs/resources/dns_record>
- `github_repository_webhook` — <https://registry.terraform.io/providers/integrations/github/latest/docs/resources/repository_webhook>

## Running

From this directory:

```sh
op run --env-file=.env -- ../tf init   # one-time per workstation
op run --env-file=.env -- ../tf plan
op run --env-file=.env -- ../tf apply
```

The `../tf` wrapper attaches to the `dockernet` Docker network so the
state backend is reachable as `http://minio:9000`. `op run` resolves
the `op://` references in `.env` to actual secrets at execution time;
no credentials hit disk. Required env vars (see `.env.example`):

| Env var | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | MinIO state-backend creds (`op://Homelab/MinIO Terraform User`). |
| `CLOUDFLARE_API_TOKEN` | Cloudflare provider auth (`op://Homelab/Cloudflare API Token`). |
| `UNIFI_API_KEY` | UniFi controller (`op://Homelab/UniFi API Key`). |
| `GITHUB_TOKEN` | GitHub webhook resource (`op://Homelab/Homelab GitHub Personal Access Token`). |
| `TF_VAR_komodo_webhook_secret` | HMAC secret shared with Komodo (`op://Homelab/Komodo Webhook Secret`). |

## Layout

| File | What's in it |
|---|---|
| `backend.tf` | S3 backend + provider version pins |
| `providers.tf` | Provider configs (auth comes from env) |
| `variables.tf` | `local.zones`, `local.tunnels`, `local.tunnel_ids` — single source of truth for zone + tunnel identifiers |
| `services_pod_haus.tf` | One `module "<name>"` per pod.haus service. Adding a service = one module block. |
| `modules/pod_haus_service/` | The module: DNS + Access app + tunnel ingress for one hostname |
| `tunnel.tf` | Aggregates every module's `ingress_rule` into the single `cloudflare_zero_trust_tunnel_cloudflared_config` resource |
| `access.tf` | Shared identity (Family group, reusable policies, service tokens) + Pine Lake apps + path-scoped Komodo webhook app + the `*.pod.haus` wildcard default-deny safety net |
| `dns_pod_haus.tf` | Non-tunnel pod.haus records (Fastmail DKIM, MX, TXT, SRV; Railway externals) |
| `dns_<other_zone>.tf` | Per-zone DNS for everything else (Fastmail mailboxes, Google Workspace domains, etc.) |
| `dns_unifi_split_horizon.tf` | UniFi-side LAN DNS overrides (`unifi.pod.haus`, `bilby.pod.haus`) |
| `github.tf` | GitHub webhook that triggers Komodo auto-deploy on push |

## Adding a new pod.haus service

```hcl
# services_pod_haus.tf
module "myservice" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "myservice"
  backend  = "http://myservice:8080"
}
```

Then add `module.myservice.ingress_rule` to the `pod_haus_module_ingress`
list in `tunnel.tf`, run `op run --env-file=.env -- ../tf apply`, done.

Default policy chain is locked: Homelab service-token bypass at
precedence 1, Family allow at precedence 2. Override with the
`access_policy_ids` input if a service needs a different chain (see
`module.paperless`, `module.syncthing`, `module.unifi` for examples).

## Adding any other Cloudflare resource

Before writing HCL, open the relevant resource page in the registry
(see the table above) and skim its schema. Provider v5 differs from
v4 in ways that aren't obvious from the v4-era examples you'll find
elsewhere on the internet.
