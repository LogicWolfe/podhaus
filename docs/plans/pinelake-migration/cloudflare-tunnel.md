# Cloudflare tunnel + Terraform

Move pinelake's tunnel ingress from on-host YAML
(`/etc/cloudflared/config.yml`) into Terraform-managed
CF-side config, matching how bilby's tunnel ingress works. Existing
DNS + Access apps are already in TF; the remaining gap is the
`cloudflare_zero_trust_tunnel_cloudflared_config` resource and a
service-module pattern for `*.pinelake.haus` mirroring
`cloudflare/modules/pod_haus_service/`.

Depends on: [Host bootstrap](host-bootstrap.md).
Coordinates with: [Flood](flood.md), [Syncthing](syncthing.md),
[Plex](plex.md).

## Current state recap

| Layer | Today | Note |
|---|---|---|
| Tunnel UUID | `fec5ca76-b634-4185-bdb2-f85c38b1b570` (named `torrent-pinelake`) | In CF; UUID literal in `cloudflare/variables.tf` |
| `cloudflared` runtime | macOS LaunchDaemon (`com.cloudflare.cloudflared.plist`), running with `--config /etc/cloudflared/config.yml` | Native, not containerised |
| Ingress source | `/etc/cloudflared/config.yml` (on-host YAML) | Drift from podhaus convention |
| TF-managed DNS | `cloudflare/dns_pinelake_haus.tf` — CNAMEs for `home`, `sync`, `torrent` → tunnel | Already correct |
| TF-managed Access apps | `cloudflare/access.tf` lines 116–168 — 3 apps, Nathan-only | Already correct, policy chain differs from `*.pod.haus` |
| TF-managed tunnel ingress | None | Gap to close |

Active ingress today:

```yaml
ingress:
  - hostname: home.pinelake.haus    → ssh://localhost:22
  - hostname: torrent.pinelake.haus → http://127.0.0.1:3000
  - hostname: sync.pinelake.haus    → http://127.0.0.1:8384  (httpHostHeader: localhost)
  - service: http_status:404
```

## Target state

```
TF source-of-truth for ingress (cloudflare_zero_trust_tunnel_cloudflared_config.pinelake)
  ├── ingress rules built from module outputs (pinelake_service module)
  └── source = "cloudflare"     <- the daemon pulls config from CF API on connect

cloudflared daemon
  └── still runs as launchd LaunchDaemon
  └── --config flag REMOVED from plist  <- forces it to pull from API
  └── /etc/cloudflared/config.yml retained for emergency local override only
```

Container option (Plan B): replicate bilby's `cloudflare-tunnel/`
compose stack on pinelake. **Default: stay LaunchDaemon.** Reasons:
- macOS daemon is already running; less moving parts to swap mid-flight.
- cloudflared in a container on macOS via colima adds an extra
  network hop (container → vz NAT → host); LaunchDaemon connects
  directly.
- The whole point of `source = "cloudflare"` is that the runtime
  shape becomes irrelevant — config lives in TF either way.

## Module: `pinelake_service`

Mirror `cloudflare/modules/pod_haus_service/` but with the
pinelake-specific defaults: Nathan-only policy chain (no Family group),
`pinelake.haus` zone, `tunnels.pinelake` tunnel target. Two ways:

1. **New module `cloudflare/modules/pinelake_service/`** — clean copy
   with different defaults. Recommended.
2. **Parameterise `pod_haus_service`** — add `zone_id`, `tunnel_target`,
   `default_*_policy_id` as required inputs (already mostly there)
   and drive them from the locals block per call. The module is
   already generic enough that this should work — the differences are
   in the call-site defaults, not the module body.

Reviewing `pod_haus_service` to choose: the module already takes
`zone_id`, `tunnel_target`, `default_bypass_policy_id`,
`default_allow_policy_id` as variables. The only thing the module
hard-codes is the **assumption that there are two default policies
(bypass + allow)**. Pinelake's current Access apps are
"Nathan-only" — single policy, no bypass, no allow.

Cleanest: **add `pinelake_service` as a fresh module** with one
`default_nathan_policy_id` input and a different default policy chain.
Or — broaden `pod_haus_service` to take a `default_policy_ids = []`
list of policy refs and skip the rest. The latter unifies, but
unification is its own decision; keep them separate for now.

### Module body sketch

`cloudflare/modules/pinelake_service/main.tf`:

```hcl
variable "account_id"              { type = string }
variable "zone_id"                 { type = string }
variable "tunnel_target"           { type = string }
variable "default_nathan_policy_id"{ type = string }

variable "hostname"  { type = string }              # e.g. "torrent"
variable "backend"   { type = string }              # e.g. "http://flood:3000"
variable "access_policy_ids" {
  type    = list(string)
  default = null    # falls back to [default_nathan_policy_id]
}
variable "origin_request" {
  type    = map(any)
  default = {}
}
variable "app_type" {
  type    = string
  default = "self_hosted"   # "ssh" for SSH-over-Access
}

locals {
  fqdn         = "${var.hostname}.pinelake.haus"
  policies     = coalesce(var.access_policy_ids, [var.default_nathan_policy_id])
}

resource "cloudflare_dns_record" "this" {
  zone_id = var.zone_id
  name    = local.fqdn
  type    = "CNAME"
  content = var.tunnel_target
  proxied = true
  ttl     = 1
}

resource "cloudflare_zero_trust_access_application" "this" {
  account_id        = var.account_id
  name              = title(replace(local.fqdn, ".", " "))
  domain            = local.fqdn
  type              = var.app_type
  session_duration  = "24h"
  policies          = local.policies
}

output "ingress_rule" {
  value = {
    hostname        = local.fqdn
    service         = var.backend
    origin_request  = var.origin_request
  }
}
```

### Call sites

`cloudflare/services_pinelake_haus.tf` (new file):

```hcl
locals {
  pinelake_service_defaults = {
    account_id               = local.account_id
    zone_id                  = local.zones["pinelake.haus"]
    tunnel_target            = local.tunnels.pinelake
    default_nathan_policy_id = cloudflare_zero_trust_access_policy.nathan_only.id
  }
}

module "pinelake_home_ssh" {
  source = "./modules/pinelake_service"
  account_id               = local.pinelake_service_defaults.account_id
  zone_id                  = local.pinelake_service_defaults.zone_id
  tunnel_target            = local.pinelake_service_defaults.tunnel_target
  default_nathan_policy_id = local.pinelake_service_defaults.default_nathan_policy_id
  hostname = "home"
  backend  = "ssh://localhost:22"
  app_type = "ssh"
}

module "pinelake_torrent" {
  source = "./modules/pinelake_service"
  account_id               = local.pinelake_service_defaults.account_id
  zone_id                  = local.pinelake_service_defaults.zone_id
  tunnel_target            = local.pinelake_service_defaults.tunnel_target
  default_nathan_policy_id = local.pinelake_service_defaults.default_nathan_policy_id
  hostname = "torrent"
  backend  = "http://172.18.0.1:3000"        # flood on dockernet, host-network
                                              # post-cutover; was http://127.0.0.1:3000
}

module "pinelake_sync" {
  source = "./modules/pinelake_service"
  account_id               = local.pinelake_service_defaults.account_id
  zone_id                  = local.pinelake_service_defaults.zone_id
  tunnel_target            = local.pinelake_service_defaults.tunnel_target
  default_nathan_policy_id = local.pinelake_service_defaults.default_nathan_policy_id
  hostname = "sync"
  backend  = "http://172.18.0.1:8384"
  origin_request = {
    httpHostHeader = "localhost"   # preserve from current YAML
  }
}
```

`cloudflare/tunnel.tf` (extend):

```hcl
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "pinelake" {
  account_id = local.account_id
  tunnel_id  = local.tunnel_ids.pinelake
  source     = "cloudflare"

  config = {
    ingress = concat(
      [
        module.pinelake_home_ssh.ingress_rule,
        module.pinelake_torrent.ingress_rule,
        module.pinelake_sync.ingress_rule,
      ],
      [
        { service = "http_status:404" }   # required catch-all
      ]
    )
  }
}
```

## Migration of existing `cloudflare/access.tf` apps

The three Access apps for pinelake are already declared in
`cloudflare/access.tf` as `pine_lake_ssh`, `pine_lake_torrent`,
`pine_lake_syncthing`. The module above would create new Access apps,
clashing with the existing ones.

Three resolution paths:

1. **Import-and-rename.** Use `terraform state mv` to rename the
   existing resources into the module's address space. Brittle for
   first-time imports; not recommended.
2. **Use existing resources via the module.** Make the module accept
   an existing `access_application_id` and skip creating one. Adds
   a flag; not clean.
3. **Replace.** Plan + apply destroys the old standalone apps and
   creates new ones inside the module. **Brief outage on each
   hostname during the apply** (probably seconds — destroy + create
   in the same transaction). Cleanest end state.

Recommendation: option 3, applied during the same window as the
cloudflared `--config` flag removal. Brief outage acceptable since
the entire migration window is already a planned change.

## cloudflared daemon plist change

Edit `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`,
remove the `--config` argument:

```diff
 <key>ProgramArguments</key>
 <array>
   <string>/opt/homebrew/bin/cloudflared</string>
-  <string>--config</string>
-  <string>/etc/cloudflared/config.yml</string>
   <string>tunnel</string>
   <string>run</string>
 </array>
```

After the edit:

```sh
sudo launchctl bootout system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```

Now cloudflared connects to the CF edge and pulls ingress config from
the API — i.e. from the TF-managed
`cloudflare_zero_trust_tunnel_cloudflared_config.pinelake`.

Verify with `cloudflared tunnel info fec5ca76-b634-4185-bdb2-f85c38b1b570`
and a curl against each hostname.

## Stale `~/.cloudflared/config.yml`

Has been irrelevant since the daemon switched to `/etc/cloudflared/`,
but it's an actively misleading file (lacks the SSH rule, lacks the
host-header override). Move to `~/.cloudflared/config.yml.archive`
post-migration to prevent confusion.

## Tunnel name

Optional rename `torrent-pinelake` → `pinelake`:

```sh
cloudflared tunnel rename fec5ca76-b634-4185-bdb2-f85c38b1b570 pinelake
```

UUID unchanged, ingress unchanged, only the display name. Cosmetic.

## cloudflared upgrade

`brew upgrade cloudflared` (covered in [Host bootstrap](host-bootstrap.md)
step 7). Do before the config migration so the daemon's CF-side
config-pull path is on the current version.

## Backend addresses through cutover

The pinelake backend addresses change as containers move:

| Service | Before migration | After (post-stack-deploy) |
|---|---|---|
| `home.pinelake.haus` | `ssh://localhost:22` | `ssh://localhost:22` (unchanged; SSH stays native) |
| `torrent.pinelake.haus` | `http://127.0.0.1:3000` (rtorrent-flood bare container) | `http://172.18.0.1:3000` (flood container on host-pub'd port via dockernet gateway) OR `http://flood:3000` if cloudflared joins dockernet |
| `sync.pinelake.haus` | `http://127.0.0.1:8384` | `http://172.18.0.1:8384` (syncthing on `network_mode: host`) |

Since cloudflared is the LaunchDaemon, `172.18.0.1:<port>` is
reachable from the host's network namespace. **Don't switch the TF
backend address before the corresponding stack deploys** — coordinate
sequencing.

Order:

1. Deploy flood stack ([Flood](flood.md)) — flood reachable at
   `172.18.0.1:3000`. Old `127.0.0.1:3000` also works for a window
   (same port published).
2. Deploy syncthing stack ([Syncthing](syncthing.md)) — syncthing
   reachable at `172.18.0.1:8384` (host-network mode).
3. **Then** TF-flip the ingress backends to `172.18.0.1`-prefixed,
   apply, remove `--config` flag from daemon plist.
4. Verify each hostname; archive the old `/etc/cloudflared/config.yml`.

## Acceptance criteria

- `cloudflare_zero_trust_tunnel_cloudflared_config.pinelake` exists
  in TF and `tf plan` is no-op
- `pinelake_service` module emits ingress rules used by the tunnel
  config resource
- cloudflared daemon runs without `--config` argument and serves all
  three hostnames
- `home.pinelake.haus` SSH still works
- `torrent.pinelake.haus`, `sync.pinelake.haus` both return their
  respective UIs through Cloudflare Access
- `/etc/cloudflared/config.yml` no longer authoritative (renamed
  `.archive`)
- No drift: `tf plan` clean

## Open items deferred

- Whether to add `plex.pinelake.haus` ingress (depends on
  [Plex](plex.md) open question #3)
- Whether to unify `pod_haus_service` and `pinelake_service` into one
  module with parameterised policy chains
- Tunnel rename (cosmetic)
- Whether cloudflared should eventually be containerised on pinelake
  too. Default: no. Revisit if there's a concrete reason.
- Access policy chain: keep Nathan-only, or add Homelab service token
  bypass for automation? Recommendation: add the Homelab bypass so
  Gatus push heartbeats can post to `*.pinelake.haus` endpoints.
  Family group not needed unless something is meant to be shared.
