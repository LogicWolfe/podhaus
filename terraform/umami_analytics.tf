# Umami analytics — per-site tracker host exposure.
#
# The shared umami container (umami/ stack) is fronted by two kinds of
# hostname:
#   - stats.pod.haus       — the DASHBOARD, Family-gated via the default
#     module chain (module.stats in services_pod_haus.tf). No public route.
#   - stats.<site>         — a per-site TRACKER host. Same-site with the
#     content domain so the tracker request isn't third-party (dodges
#     adblock / third-party-cookie heuristics). This file wires the
#     nathanbaxter.com tracker; skycroeser.net's is deliberately NOT here
#     yet (Sky rolls out after nathanbaxter.com is verified).
#
# Lock-the-host / open-the-subroutes, the same mechanism as the Komodo
# webhook bypass (access.tf): Cloudflare Access matches the most-specific
# Application, so a host-level Family app locks the whole tracker host
# (dashboard, admin API, everything) while two path-scoped bypass apps
# punch public holes for exactly the two routes a visitor's browser
# needs — the tracker script and the event-collection endpoint. The
# dashboard is therefore never publicly reachable on any hostname, and
# Umami's own login sits behind Cloudflare Access rather than in front of
# the public internet.
#
# Reference: https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_access_application

# --- DNS: stats.nathanbaxter.com → pod_haus tunnel → Caddy-less direct
# to umami (tunnel ingress in tunnel.tf). Proxied (orange-cloud): plain
# HTTP analytics, no SigV4 — Cloudflare's proxy is correct here.
resource "cloudflare_dns_record" "stats_nathanbaxter_com" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "stats.nathanbaxter.com"
  type    = "CNAME"
  content = local.tunnels.pod_haus
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

# --- Host-level lock: everything on stats.nathanbaxter.com is gated to
# Family (Homelab service-token bypass first so automation — e.g. the
# Umami setup API call — can reach it, then Family browser login). The
# two path apps below override this for their specific routes.
resource "cloudflare_zero_trust_access_application" "stats_nathanbaxter_host" {
  account_id          = var.account_id
  name                = "stats.nathanbaxter.com (dashboard)"
  type                = "self_hosted"
  domain              = "stats.nathanbaxter.com"
  self_hosted_domains = ["stats.nathanbaxter.com"]
  session_duration    = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.pod_haus_family_allow.id },
  ]
}

# --- Public hole 1: the tracker script the visitor's browser loads.
resource "cloudflare_zero_trust_access_application" "stats_nathanbaxter_script" {
  account_id          = var.account_id
  name                = "stats.nathanbaxter.com /script.js (public)"
  type                = "self_hosted"
  domain              = "stats.nathanbaxter.com/script.js"
  self_hosted_domains = ["stats.nathanbaxter.com/script.js"]
  session_duration    = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  # Browsers may send a CORS preflight before posting; let it through.
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}

# --- Public hole 2: the event-collection endpoint the script POSTs to.
resource "cloudflare_zero_trust_access_application" "stats_nathanbaxter_send" {
  account_id          = var.account_id
  name                = "stats.nathanbaxter.com /api/send (public)"
  type                = "self_hosted"
  domain              = "stats.nathanbaxter.com/api/send"
  self_hosted_domains = ["stats.nathanbaxter.com/api/send"]
  session_duration    = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}
