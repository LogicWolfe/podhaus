# Umami analytics — per-site tracker host exposure.
#
# The shared umami container (umami/ stack) is fronted by two kinds of
# hostname:
#   - stats.pod.haus       — the DASHBOARD, Family-gated via the default
#     module chain (module.stats in services_pod_haus.tf). No public route.
#   - stats.<site>         — a per-site TRACKER host. Same-site with the
#     content domain so the tracker request isn't third-party (dodges
#     adblock / third-party-cookie heuristics). This file wires the
#     nathanbaxter.com, pets.indigopod.au, and skycroeser.net trackers.
#
# Per-site pattern (repeated inline per site below): DNS CNAME → tunnel,
# a host-level Family Access app, two path-scoped public-bypass apps
# (/script.js + /api/send), and a root → share-view redirect ruleset.
# The tracker host is one level under the registrable domain so it stays
# inside Cloudflare's single-level Universal SSL wildcard — pets uses
# stats.indigopod.au (not stats.pets.indigopod.au, which the *.indigopod.au
# cert wouldn't cover); it's still same-site with pets.indigopod.au.
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
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

# --- Host-level lock: everything on stats.nathanbaxter.com is gated to
# Family (Homelab service-token bypass first so automation — e.g. the
# Umami setup API call — can reach it, then Family browser login). The
# two path apps below override this for their specific routes.
resource "cloudflare_zero_trust_access_application" "stats_nathanbaxter_host" {
  account_id       = var.account_id
  name             = "stats.nathanbaxter.com (dashboard)"
  type             = "self_hosted"
  domain           = "stats.nathanbaxter.com"
  destinations     = [{ type = "public", uri = "stats.nathanbaxter.com" }]
  session_duration = "730h"

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
  account_id       = var.account_id
  name             = "stats.nathanbaxter.com /script.js (public)"
  type             = "self_hosted"
  domain           = "stats.nathanbaxter.com/script.js"
  destinations     = [{ type = "public", uri = "stats.nathanbaxter.com/script.js" }]
  session_duration = "730h"

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
  account_id       = var.account_id
  name             = "stats.nathanbaxter.com /api/send (public)"
  type             = "self_hosted"
  domain           = "stats.nathanbaxter.com/api/send"
  destinations     = [{ type = "public", uri = "stats.nathanbaxter.com/api/send" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}

# --- Make stats.<site> the no-login viewing entry: redirect ONLY the
# bare root to that site's Umami Share URL. Umami's /share/<id>/<domain>
# page is unauthenticated (self-fetches a read-only scoped token), so
# behind the Family-gated host it gives "Cloudflare login → stats, no
# Umami prompt". The match is path == "/" exactly, so the tracker
# (/script.js, /api/send) and the share page itself (/share/*, /api/*,
# /_next/*) are untouched. stats.pod.haus is deliberately NOT redirected
# — it stays the admin dashboard (Umami login for management).
#
# The shareId is Umami DB state (set via the API, backed up in pgdata).
# If it's ever regenerated, update this value + the site's snippet.
resource "cloudflare_ruleset" "nathanbaxter_stats_redirect" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "stats.nathanbaxter.com root → share view"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"

  rules = [{
    ref         = "stats_nathanbaxter_root_to_share"
    description = "Bare root of the tracker host → the read-only share dashboard"
    expression  = "(http.host eq \"stats.nathanbaxter.com\" and http.request.uri.path eq \"/\")"
    action      = "redirect"
    enabled     = true
    action_parameters = {
      from_value = {
        status_code           = 302
        preserve_query_string = false
        target_url = {
          value = "https://stats.nathanbaxter.com/share/BRudfaqCQRTlnGYa/nathanbaxter.com"
        }
      }
    }
  }]
}

# =============================================================================
# pets.indigopod.au — Indigo's pet game (public, no Access on the game
# itself). Tracker host is stats.indigopod.au (second-level, Universal-SSL
# covered; same registrable domain as pets.indigopod.au so still same-site).
# =============================================================================

resource "cloudflare_dns_record" "stats_indigopod_au" {
  zone_id = local.zones["indigopod.au"]
  name    = "stats.indigopod.au"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

# Host-level lock: dashboard/admin on stats.indigopod.au gated to Family.
resource "cloudflare_zero_trust_access_application" "stats_indigopod_host" {
  account_id       = var.account_id
  name             = "stats.indigopod.au (dashboard)"
  type             = "self_hosted"
  domain           = "stats.indigopod.au"
  destinations     = [{ type = "public", uri = "stats.indigopod.au" }]
  session_duration = "730h"

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

# Public hole 1: the tracker script the player's browser loads.
resource "cloudflare_zero_trust_access_application" "stats_indigopod_script" {
  account_id       = var.account_id
  name             = "stats.indigopod.au /script.js (public)"
  type             = "self_hosted"
  domain           = "stats.indigopod.au/script.js"
  destinations     = [{ type = "public", uri = "stats.indigopod.au/script.js" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}

# Public hole 2: the event-collection endpoint the script POSTs to.
resource "cloudflare_zero_trust_access_application" "stats_indigopod_send" {
  account_id       = var.account_id
  name             = "stats.indigopod.au /api/send (public)"
  type             = "self_hosted"
  domain           = "stats.indigopod.au/api/send"
  destinations     = [{ type = "public", uri = "stats.indigopod.au/api/send" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}

# Root → the pets share view (read-only, Family-gated). shareId is Umami
# DB state (set via API, backed up in pgdata); regenerating it means
# updating this value + the game's snippet.
resource "cloudflare_ruleset" "indigopod_stats_redirect" {
  zone_id = local.zones["indigopod.au"]
  name    = "stats.indigopod.au root → share view"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"

  rules = [{
    ref         = "stats_indigopod_root_to_share"
    description = "Bare root of the tracker host → the read-only share dashboard"
    expression  = "(http.host eq \"stats.indigopod.au\" and http.request.uri.path eq \"/\")"
    action      = "redirect"
    enabled     = true
    action_parameters = {
      from_value = {
        status_code           = 302
        preserve_query_string = false
        target_url = {
          value = "https://stats.indigopod.au/share/xc2sfWOKuH3EbeXy/pets.indigopod.au"
        }
      }
    }
  }]
}

# =============================================================================
# skycroeser.net — Sky's academic site (public Publii static site; see
# dns_skycroeser_net.tf). Tracker host stats.skycroeser.net is same-site
# with the content domain and one level under the registrable domain, so
# Universal SSL covers it. Sky views her stats via the root → share-view
# redirect (she's in the Family Access group).
# =============================================================================

resource "cloudflare_dns_record" "stats_skycroeser_net" {
  zone_id = local.zones["skycroeser.net"]
  name    = "stats.skycroeser.net"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

# Host-level lock: dashboard/admin on stats.skycroeser.net gated to Family.
resource "cloudflare_zero_trust_access_application" "stats_skycroeser_host" {
  account_id       = var.account_id
  name             = "stats.skycroeser.net (dashboard)"
  type             = "self_hosted"
  domain           = "stats.skycroeser.net"
  destinations     = [{ type = "public", uri = "stats.skycroeser.net" }]
  session_duration = "730h"

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

# Public hole 1: the tracker script the visitor's browser loads.
resource "cloudflare_zero_trust_access_application" "stats_skycroeser_script" {
  account_id       = var.account_id
  name             = "stats.skycroeser.net /script.js (public)"
  type             = "self_hosted"
  domain           = "stats.skycroeser.net/script.js"
  destinations     = [{ type = "public", uri = "stats.skycroeser.net/script.js" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}

# Public hole 2: the event-collection endpoint the script POSTs to.
resource "cloudflare_zero_trust_access_application" "stats_skycroeser_send" {
  account_id       = var.account_id
  name             = "stats.skycroeser.net /api/send (public)"
  type             = "self_hosted"
  domain           = "stats.skycroeser.net/api/send"
  destinations     = [{ type = "public", uri = "stats.skycroeser.net/api/send" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = false
  http_only_cookie_attribute = true

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.public_bypass.id },
  ]
}

# Root → the skycroeser.net share view (read-only, Family-gated). shareId
# is Umami DB state (set via API, backed up in pgdata); regenerating it
# means updating this value + the site's snippet.
resource "cloudflare_ruleset" "skycroeser_stats_redirect" {
  zone_id = local.zones["skycroeser.net"]
  name    = "stats.skycroeser.net root → share view"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"

  rules = [{
    ref         = "stats_skycroeser_root_to_share"
    description = "Bare root of the tracker host → the read-only share dashboard"
    expression  = "(http.host eq \"stats.skycroeser.net\" and http.request.uri.path eq \"/\")"
    action      = "redirect"
    enabled     = true
    action_parameters = {
      from_value = {
        status_code           = 302
        preserve_query_string = false
        target_url = {
          value = "https://stats.skycroeser.net/share/akYfaxpJqfylsF7D/skycroeser.net"
        }
      }
    }
  }]
}
