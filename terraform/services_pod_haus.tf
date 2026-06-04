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

  # kangaroo (QNAP) LAN IP — single source of truth, consumed by its
  # Cloudflare-tunnel backends AND the UniFi DHCP reservation
  # (unifi_user.kangaroo, pinned to eth0's MAC). Change here to renumber.
  kangaroo_lan_ip = "10.0.0.232"

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

module "bugsink" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
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
  backend  = "http://${local.kangaroo_lan_ip}:9898"
}

module "kangaroo" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  hostname = "kangaroo"
  backend  = "http://${local.kangaroo_lan_ip}:8080"
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

# logs.pod.haus (VictoriaLogs vmui) and grafana.pod.haus were removed
# when ClickStack/HyperDX (watch.pod.haus) replaced them — see
# docs/plans/clickstack-migration/cutover.md Phase D.

module "watch" {
  source = "./modules/pod_haus_service"

  account_id               = local.pod_haus_service_defaults.account_id
  zone_id                  = local.pod_haus_service_defaults.zone_id
  tunnel_target            = local.pod_haus_service_defaults.tunnel_target
  default_bypass_policy_id = local.pod_haus_service_defaults.default_bypass_policy_id
  default_allow_policy_id  = local.pod_haus_service_defaults.default_allow_policy_id

  # HyperDX (ClickStack UI) — replaces logs.pod.haus (VL vmui) +
  # grafana.pod.haus. Those modules stay until decommission (Phase D);
  # watch goes up alongside them. Default chain: Homelab service-token
  # bypass → Family allow, same as the rest of the fleet.
  hostname = "watch"
  backend  = "http://hyperdx:8080"
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
  backend  = "http://${local.kangaroo_lan_ip}:8384"

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

# storage.pod.haus is NOT a Cloudflare-proxied service. Its S3 API is
# served via its own Caddy + LE wildcard behind a UniFi port-forward,
# with grey-cloud (DNS-only) records in dns_storage.tf — Cloudflare's
# HTTP proxy mangles SigV4 (Accept-Encoding) and its single-level cert
# can't cover Publii's virtual-host buckets. See
# docs/plans/minio-public-caddy.md.
