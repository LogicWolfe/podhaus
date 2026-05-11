# Cloudflare Access — identity-gated reverse proxy.
#
# Topology:
#   - One account-level Family group (email_domain + explicit emails)
#   - One reusable "Nathan" policy (used by the Pine Lake apps)
#   - One reusable "Homelab service token" bypass policy (NEW — service
#     token gates programmatic access across the *.pod.haus surface)
#   - 10 existing Applications, each gating one or more hostnames
#   - 2 NEW Applications:
#       * Komodo webhook bypass (path-scoped, future Railway driver)
#       * Paperless iOS (mobile app with a dedicated service token)
#
# More-specific Application matches take precedence over the
# `*.pod.haus` wildcard, so per-host apps act as overrides and their
# attached policies fully replace the wildcard's policy for those hosts.

locals {
  pod_haus_app_overrides = [
    cloudflare_zero_trust_access_application.home_assistant,
    cloudflare_zero_trust_access_application.sunshine,
    cloudflare_zero_trust_access_application.syncthing,
    cloudflare_zero_trust_access_application.torrents,
  ]
}

# ============================================================================
# Identity — group + reusable policies
# ============================================================================

resource "cloudflare_zero_trust_access_group" "family" {
  account_id = var.account_id
  name       = "Family"

  include = [
    { email_domain = { domain = "nathanbaxter.com" } },
    { email_domain = { domain = "pod.haus" } },
    { email        = { email = "scroeser@gmail.com" } },
  ]
}

resource "cloudflare_zero_trust_access_policy" "nathan" {
  account_id = var.account_id
  name       = "Nathan"
  decision   = "allow"
  include = [
    { email = { email = "nathan@nathanbaxter.com" } },
  ]
}

resource "cloudflare_zero_trust_access_policy" "homelab_service_token_bypass" {
  account_id = var.account_id
  name       = "Service token: Homelab bypass"
  decision   = "bypass"
  include = [
    { service_token = { token_id = cloudflare_zero_trust_access_service_token.homelab.id } },
  ]
}

resource "cloudflare_zero_trust_access_policy" "paperless_ios_bypass" {
  account_id = var.account_id
  name       = "Service token: Paperless iOS"
  decision   = "bypass"
  include = [
    { service_token = { token_id = cloudflare_zero_trust_access_service_token.paperless_ios.id } },
  ]
}

# ============================================================================
# Service tokens
# ============================================================================

resource "cloudflare_zero_trust_access_service_token" "homelab" {
  account_id = var.account_id
  name       = "Homelab service token"
  duration   = "8760h" # 1 year — rotate proactively
}

resource "cloudflare_zero_trust_access_service_token" "paperless_ios" {
  account_id = var.account_id
  name       = "Paperless iOS"
  duration   = "8760h"
}

# ============================================================================
# Existing Applications (imported)
# ============================================================================

# UniFi has its own login page; bypass CF Access entirely.
resource "cloudflare_zero_trust_access_application" "unifi" {
  account_id           = var.account_id
  name                 = "UniFi (bypass — own auth)"
  type                 = "self_hosted"
  domain               = "unifi.pod.haus"
  self_hosted_domains  = ["unifi.pod.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = false
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.unifi_bypass.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "unifi_bypass" {
  account_id = var.account_id
  name       = "Bypass — UniFi has its own login"
  decision   = "bypass"
  include    = [{ everyone = {} }]
}

# Pod Haus wildcard — the default deny-by-default gate for everything
# not covered by a more-specific Application.
resource "cloudflare_zero_trust_access_application" "pod_haus_wildcard" {
  account_id           = var.account_id
  name                 = "Pod Haus wildcard (default-deny)"
  type                 = "self_hosted"
  domain               = "*.pod.haus"
  self_hosted_domains  = ["*.pod.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = false
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.pod_haus_family_allow.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "pod_haus_family_allow" {
  account_id = var.account_id
  name       = "Family allow"
  decision   = "allow"
  include    = [{ group = { id = cloudflare_zero_trust_access_group.family.id } }]
}

# Pine Lake — household-specific, only Nathan, no Family group.
resource "cloudflare_zero_trust_access_application" "pine_lake_ssh" {
  account_id           = var.account_id
  name                 = "Pine Lake SSH"
  type                 = "ssh"
  domain               = "home.pinelake.haus"
  self_hosted_domains  = ["home.pinelake.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = true
  http_only_cookie_attribute= false
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
  ]
}

resource "cloudflare_zero_trust_access_application" "pine_lake_torrent" {
  account_id           = var.account_id
  name                 = "Pine Lake Torrent"
  type                 = "self_hosted"
  domain               = "torrent.pinelake.haus"
  self_hosted_domains  = ["torrent.pinelake.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = true
  app_launcher_visible      = true
  http_only_cookie_attribute= false
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
  ]
}

resource "cloudflare_zero_trust_access_application" "pine_lake_syncthing" {
  account_id           = var.account_id
  name                 = "Pine Lake Syncthing"
  type                 = "self_hosted"
  domain               = "sync.pinelake.haus"
  self_hosted_domains  = ["sync.pinelake.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = true
  app_launcher_visible      = true
  http_only_cookie_attribute= false
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
  ]
}

# Home Assistant — Family-gated, with the Homelab service token bypass
# layered on top for automation.
resource "cloudflare_zero_trust_access_application" "home_assistant" {
  account_id           = var.account_id
  name                 = "Home Assistant"
  type                 = "self_hosted"
  domain               = "home.pod.haus"
  self_hosted_domains  = ["home.pod.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = true
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.home_assistant_family.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "home_assistant_family" {
  account_id = var.account_id
  name       = "Allow"
  decision   = "allow"
  include    = [{ group = { id = cloudflare_zero_trust_access_group.family.id } }]
}

resource "cloudflare_zero_trust_access_application" "sunshine" {
  account_id           = var.account_id
  name                 = "Sunshine"
  type                 = "self_hosted"
  domain               = "sunshine.pod.haus"
  self_hosted_domains  = ["sunshine.pod.haus"]
  session_duration     = "24h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = true
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.sunshine_family.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "sunshine_family" {
  account_id = var.account_id
  name       = "Family"
  decision   = "allow"
  include    = [{ group = { id = cloudflare_zero_trust_access_group.family.id } }]
}

resource "cloudflare_zero_trust_access_application" "syncthing" {
  account_id           = var.account_id
  name                 = "Syncthing"
  type                 = "self_hosted"
  domain               = "sync.pod.haus"
  self_hosted_domains  = ["sync.pod.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = true
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.syncthing_nathan.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "syncthing_nathan" {
  account_id = var.account_id
  name       = "Nathan"
  decision   = "allow"
  # Note: capital N existing in CF — preserved to avoid drift.
  include    = [{ email = { email = "Nathan@nathanbaxter.com" } }]
}

resource "cloudflare_zero_trust_access_application" "torrents" {
  account_id           = var.account_id
  name                 = "Torrents"
  type                 = "self_hosted"
  domain               = "torrent.pod.haus"
  self_hosted_domains  = ["torrent.pod.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = true
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.torrents_family.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "torrents_family" {
  account_id = var.account_id
  name       = "Family"
  decision   = "allow"
  include    = [{ group = { id = cloudflare_zero_trust_access_group.family.id } }]
}

# App Launcher — Cloudflare's SaaS app picker UI.
resource "cloudflare_zero_trust_access_application" "app_launcher" {
  account_id       = var.account_id
  name             = "App Launcher"
  type             = "app_launcher"
  session_duration = "24h"

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.app_launcher_family.id },
  ]

  # Provider v5 wants to inject `{title = "Welcome!"}` on every refresh
  # for app_launcher-type apps. Set landing_page_design to an empty
  # block explicitly so we don't churn on every plan.
  landing_page_design = {}

  lifecycle {
    ignore_changes = [landing_page_design]
  }
}
resource "cloudflare_zero_trust_access_policy" "app_launcher_family" {
  account_id = var.account_id
  name       = "Family"
  decision   = "allow"
  include    = [{ group = { id = cloudflare_zero_trust_access_group.family.id } }]
}

# ============================================================================
# NEW Applications
# ============================================================================

# Paperless iOS — domain-specific app overrides the wildcard so the
# Paperless service token bypass is bounded to this one host.
resource "cloudflare_zero_trust_access_application" "paperless" {
  account_id           = var.account_id
  name                 = "Paperless"
  type                 = "self_hosted"
  domain               = "paperless.pod.haus"
  self_hosted_domains  = ["paperless.pod.haus"]
  session_duration     = "730h"

  auto_redirect_to_identity = false
  enable_binding_cookie     = false
  options_preflight_bypass  = false
  app_launcher_visible      = true
  http_only_cookie_attribute= true
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.paperless_ios_bypass.id },
    { precedence = 2, id = cloudflare_zero_trust_access_policy.homelab_service_token_bypass.id },
    { precedence = 3, id = cloudflare_zero_trust_access_policy.paperless_family.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "paperless_family" {
  account_id = var.account_id
  name       = "Family"
  decision   = "allow"
  include    = [{ group = { id = cloudflare_zero_trust_access_group.family.id } }]
}

# Komodo webhook bypass — Railway-migration driver.
# Path-scoped Application gating only the GitHub webhook delivery URL;
# bypasses Access for the service-token-bearing request, leaves the
# rest of komodo.pod.haus on the wildcard gate.
resource "cloudflare_zero_trust_access_application" "komodo_webhook" {
  account_id           = var.account_id
  name                 = "Komodo webhook (bypass)"
  type                 = "self_hosted"
  domain               = "komodo.pod.haus/auth/github/webhook"
  self_hosted_domains  = ["komodo.pod.haus/auth/github/webhook"]
  session_duration     = "24h"

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.komodo_webhook_bypass.id },
  ]
}
resource "cloudflare_zero_trust_access_policy" "komodo_webhook_bypass" {
  account_id = var.account_id
  name       = "Bypass — Komodo validates the HMAC"
  decision   = "bypass"
  include    = [{ everyone = {} }]
}
