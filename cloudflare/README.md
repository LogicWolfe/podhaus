# cloudflare/

Terraform-managed Cloudflare Account resources. State lives in MinIO at
`s3://terraform-state/cloudflare.tfstate` (see
[Terraform foundation](../docs/plans/alligator-bilby-migration/terraform-setup.md)).

## Running

From this directory:

```sh
op run --env-file=.env -- ../tf init   # one-time per workstation
op run --env-file=.env -- ../tf plan
op run --env-file=.env -- ../tf apply
```

The `../tf` wrapper attaches to the `dockernet` Docker network so the
state backend is reachable as `http://minio:9000`; `op run` resolves
`.env`'s `op://` refs to:

- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — `op://Homelab/MinIO Terraform User/…`
- `CLOUDFLARE_API_TOKEN` — `op://Homelab/Cloudflare API Token/credential`

## Layout

| File | What's in it |
|---|---|
| `backend.tf` | S3 backend → MinIO + Cloudflare provider v5 pin |
| `providers.tf` | Cloudflare provider config (token from env) |
| `variables.tf` | `local.zones` (zone IDs) + `local.tunnels` (tunnel CNAMEs) |
| `dns_pod_haus.tf` | All `pod.haus` DNS records — tunnel CNAMEs (for_each), external CNAMEs, MX, TXT |

## Migration status (2026-05-11)

Initial migration off DNSControl is in progress:

- ✓ `pod.haus` — 26 records, zero drift
- pending: the other 10 zones (pinelake.haus, elusive.email,
  fractalseed.com, logicaldecay.{com,net}, logicwolfe.com,
  nathanbaxter.{com,net,org}, podfoundation.org.au)
- pending: 10 Cloudflare Access Applications + their policies
- pending: rulesets, transform rules, cache rules, zone settings
- pending: new Komodo webhook bypass Access app
- pending: new Paperless iOS service-token Access app

DNSControl in `dns/` is still authoritative for everything except
`pod.haus`. Apply through Terraform here, preview/plan through both
during the parallel period.

## Patterns

Import an existing CF resource into state, generate scaffold HCL, then
clean up:

```sh
# 1. Discover record IDs:
curl -sf "https://api.cloudflare.com/client/v4/zones/<zone>/dns_records?per_page=200" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | jq '.result[] | {id, type, name}'

# 2. Add `import { to = ..., id = "<zone>/<record>" }` blocks to a
#    throwaway file (e.g. imports_<zone>.tf).

# 3. Auto-generate scaffolds, then review:
../tf plan -generate-config-out=generated_<zone>.tf

# 4. Apply imports — moves resources into state:
../tf apply -auto-approve

# 5. Hand-clean the generated config into dns_<zone>.tf
#    (use for_each where records repeat, reference local.zones[...]
#    and local.tunnels[...] instead of hardcoded IDs).

# 6. terraform state mv each old per-record address to the new
#    for_each-keyed address.

# 7. Delete imports_<zone>.tf + generated_<zone>.tf, run `../tf plan`,
#    confirm zero drift, commit.
```

### Known schema quirks (provider v5)

- **SRV records** and **URI records** use the `data { … }` attribute
  instead of `content`. The `terraform plan -generate-config-out` flow
  emits BOTH and the resulting HCL fails validation. Hand-write these
  resources from API output:

  ```hcl
  resource "cloudflare_dns_record" "nathanbaxter_com_srv_caldavs" {
    zone_id  = local.zones["nathanbaxter.com"]
    name     = "_caldavs._tcp.nathanbaxter.com"
    type     = "SRV"
    ttl      = 1
    proxied  = false
    data = {
      priority = 0
      weight   = 1
      port     = 443
      target   = "caldav.fastmail.com"
    }
  }
  ```

- **Tunnel-routed CNAMEs** use `proxied = true` and `ttl = 1` (auto);
  external CNAMEs use `proxied = false` and `ttl = 300`. Mixing these
  in one `for_each` is awkward — split into two resources (see
  `dns_pod_haus.tf`).

- The provider may surface `comment` on records that DNSControl never
  set. If `tf plan` wants to drop a `comment`, preserve it in HCL —
  some records like the Postmark DKIM have hand-set comments worth
  keeping.
