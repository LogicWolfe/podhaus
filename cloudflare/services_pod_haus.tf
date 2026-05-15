# pod.haus service exposure — one module instance per single-host
# Access-gated service. The module owns DNS CNAME + Access app +
# default-locked policy chain + tunnel ingress rule.
#
# Adding a service: drop a `module "<name>"` block here, `../tf plan`,
# `../tf apply`. That's it.
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

  pod_haus_service_defaults = {
    account_id               = var.account_id
    zone_id                  = local.zones["pod.haus"]
    tunnel_target            = local.tunnels.pod_haus
    default_bypass_policy_id = local.default_pod_haus_bypass_policy
    default_allow_policy_id  = local.default_pod_haus_allow_policy
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
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "gatus"
  backend  = "http://gatus:8080"
}

module "backup" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
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
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "kangaroo-backup"
  backend  = "http://10.0.0.25:9898"
}

module "kangaroo" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "kangaroo"
  backend  = "http://10.0.0.25:8080"
}

module "komodo" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
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
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "plex"
  backend  = "http://172.18.0.1:32400"
}

module "logs" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "logs"
  backend  = "http://victoria-logs:9428"
}

module "grafana" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "grafana"
  backend  = "http://grafana:3000"
}

module "docs" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "docs"
  backend  = "http://docs-server:80"
}

module "minio" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
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

  hostname = "sync"
  backend  = "http://10.0.0.25:8384"

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

  hostname             = "unifi"
  backend              = "https://10.0.0.1:443"
  origin_request       = { no_tls_verify = true }
  app_launcher_visible = false

  access_policy_ids = [
    cloudflare_zero_trust_access_policy.unifi_bypass.id,
  ]
}
