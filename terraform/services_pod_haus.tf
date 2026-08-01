# pod.haus service exposure — one module instance per single-host
# Access-gated service. The module owns DNS CNAME + Access app +
# default-locked policy chain + tunnel ingress rule.
#
# Adding a service: drop a `module "<name>"` block here, then run stock
# `terraform plan` and `terraform apply` from this directory.
#
# Reference docs:
#   - Cloudflare provider:    https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs
#   - dns_record:             https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/dns_record
#   - access_application:     https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_application
#   - tunnel_cloudflared_config: https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config

locals {
  # Default policy chain for any service that doesn't override. Order
  # is precedence-ascending: service-token bypass first (so automation
  # short-circuits the login), Family allow second (so the household
  # can browser-login).
  default_pod_haus_bypass_policy = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id
  default_pod_haus_allow_policy  = cloudflare_zero_trust_access_policy.pod_haus_family_allow.id

  # kangaroo (QNAP) LAN IPs — two NICs, two live reservations:
  #   kangaroo_ip_1g  → eth0 (1GbE, MAC …78:bf), the spare path
  #   kangaroo_ip_10g → eth1 (10GbE, MAC …78:c0), the active path
  # kangaroo_active_ip is the cutover knob the tunnel backends point at;
  # flip it to kangaroo_ip_1g to fail back onto 1GbE. Both reservations
  # stay live — QTS sets arp_ignore=1/arp_announce=2 so the two IPs
  # coexist on the subnet without ARP flux.
  kangaroo_ip_1g     = "10.0.0.232"
  kangaroo_ip_10g    = "10.0.0.25"
  kangaroo_active_ip = local.kangaroo_ip_10g

  pod_haus_service_defaults = {
    account_id               = var.account_id
    zone_id                  = local.zones["pod.haus"]
    tunnel_target            = local.tunnels.pod_haus
    default_bypass_policy_id = local.default_pod_haus_bypass_policy
    default_allow_policy_id  = local.default_pod_haus_allow_policy
    edge_ipv4                = local.numbat_application_ipv4
  }
}

# -----------------------------------------------------------------------------
# Services using the default locked-by-default chain
# (Homelab service-token bypass → Family allow)
# -----------------------------------------------------------------------------

module "gatus" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "gatus"
  backend  = "http://gatus:8080"
}

module "bugsink" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "bugs"
  backend  = "http://bugsink:8000"
}

module "backup" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "backup"
  backend  = "http://backrest:9898"
}

module "fenwick" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "fenwick"
  backend  = "http://fenwick:8088"
}

module "kangaroo_backup" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "kangaroo-backup"
  backend  = "http://${local.kangaroo_active_ip}:9898"
}

module "kangaroo" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "kangaroo"
  backend  = "http://${local.kangaroo_active_ip}:8080"
}

module "komodo" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "komodo"
  backend  = "http://komodo-core:9120"
}

module "torrents" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "torrent"
  backend  = "http://flood:3000"
}

module "home_assistant" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "home"
  backend  = "http://172.18.0.1:8123"
}

module "plex" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "plex"
  backend  = "http://172.18.0.1:32400"
}

# Music Assistant web UI. Host-network on bilby (like HA/Plex), reached
# by cloudflared over the dockernet gateway. This fronts ONLY the 8095
# web UI + the HA OAuth login redirect — the AirPlay audio stream (8097)
# is a direct LAN fetch by the speaker and is handled by the firewall
# (bilby/firewalld/), not the tunnel.
module "music" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "music"
  backend  = "http://172.18.0.1:8095"
}

# ClickStack/HyperDX is exposed at watch.pod.haus.

module "watch" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  # Default chain: Homelab service-token bypass, then Family allow.
  hostname = "watch"
  backend  = "http://hyperdx:8080"
}

module "docs" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  # The central docs service (FastAPI/Granian, repo LogicWolfe/docs-server),
  # replacing the legacy static-nginx docs-server. Cut over by repointing this
  # backend once the new `docs` stack is verified up; revert this one line to
  # roll back to nginx.
  hostname = "docs"
  backend  = "http://docs:8000"
}

module "minio" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "minio"
  backend  = "http://minio:9001"
}

# -----------------------------------------------------------------------------
# Services with custom policy chains (override the locked-by-default)
# -----------------------------------------------------------------------------

# Syncthing — Nathan only (the household share is private). Reuses the
# shared `nathan` reusable policy that Pine Lake apps also use.
module "syncthing" {
  source = "./modules/pod_haus_service"

  account_id    = local.pod_haus_service_defaults.account_id
  zone_id       = local.pod_haus_service_defaults.zone_id
  tunnel_target = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4     = local.pod_haus_service_defaults.edge_ipv4

  hostname = "sync"
  backend  = "http://${local.kangaroo_active_ip}:8384"

  access_policy_ids = [
    cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id,
    cloudflare_zero_trust_access_policy.nathan.id,
  ]
}

# Paperless — three-policy chain. Paperless-iOS service token first
# (mobile app), Homelab service token next (general automation),
# Family allow last (browser login).
module "paperless" {
  source = "./modules/pod_haus_service"

  account_id    = local.pod_haus_service_defaults.account_id
  zone_id       = local.pod_haus_service_defaults.zone_id
  tunnel_target = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4     = local.pod_haus_service_defaults.edge_ipv4

  hostname = "paperless"
  backend  = "http://paperless:8000"

  access_policy_ids = [
    cloudflare_zero_trust_access_policy.paperless_ios_bypass.id,
    cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id,
    cloudflare_zero_trust_access_policy.pod_haus_family_allow.id,
  ]
}

# UniFi — own login page. Single Bypass policy (everyone) means CF
# Access does no auth at all; UniFi handles user identity itself.
module "unifi" {
  source = "./modules/pod_haus_service"

  account_id    = local.pod_haus_service_defaults.account_id
  zone_id       = local.pod_haus_service_defaults.zone_id
  tunnel_target = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4     = local.numbat_relay_ipv4

  hostname             = "unifi"
  backend              = "https://10.0.0.1:443"
  origin_request       = { no_tls_verify = true }
  app_launcher_visible = false

  access_policy_ids = [
    cloudflare_zero_trust_access_policy.unifi_bypass.id,
  ]
}

# id.pod.haus — the Pocket ID OIDC identity provider itself. MUST be
# publicly reachable so Cloudflare's servers can fetch the OIDC token/JWKS
# endpoints during login (a Family-gated id.pod.haus would deadlock the
# "fresh keys" verification). A bypass-everyone policy overrides the
# *.pod.haus wildcard's Family gate — same mechanism as module.unifi.
# Pocket ID's own passkey login protects the admin UI.
# See docs/runbooks/pocket-id.md.
module "pocket_id" {
  source = "./modules/pod_haus_service"

  account_id    = local.pod_haus_service_defaults.account_id
  zone_id       = local.pod_haus_service_defaults.zone_id
  tunnel_target = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4     = local.numbat_relay_ipv4

  hostname = "id"
  backend  = "http://pocket-id:1411"

  access_policy_ids = [
    cloudflare_zero_trust_access_policy.public_bypass.id,
  ]
}

# stats.pod.haus — the Umami analytics DASHBOARD. Default locked chain
# (Homelab service-token bypass → Family allow), so viewing analytics is
# gated by Cloudflare Access. The public tracker endpoints live on the
# per-site `stats.<site>` hosts (umami_analytics.tf), never here — this
# host has no public route at all. backend is the shared umami container.
module "stats" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  edge_ipv4                = local.pod_haus_service_defaults.edge_ipv4
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "stats"
  backend  = "http://umami:3000"
}

# storage.pod.haus is NOT a Cloudflare-proxied service. Its S3 API is
# served via Caddy and its own LE wildcard behind the Kookaburra relay,
# with grey-cloud (DNS-only) records in dns_storage.tf — Cloudflare's
# HTTP proxy mangles SigV4 (Accept-Encoding) and its single-level cert
# can't cover Publii's virtual-host buckets. See docs/hosts.html.
