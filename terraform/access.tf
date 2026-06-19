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

# UniFi bypass — referenced by module.unifi (see services_pod_haus.tf).
# The Application resource itself is owned by the module.
resource "cloudflare_zero_trust_access_policy" "unifi_bypass" {
  account_id = var.account_id
  name       = "Bypass — UniFi has its own login"
  decision   = "bypass"
  include    = [{ everyone = {} }]
}

# Public bypass — everyone, no auth. Reusable across genuinely public
# hostnames that override the *.pod.haus wildcard's Family gate (e.g.
# sky.pod.haus static site; future public sites/endpoints share it).
# The site itself carries no secrets; MinIO SigV4 guards the publish
# path separately on storage.pod.haus.
resource "cloudflare_zero_trust_access_policy" "public_bypass" {
  account_id = var.account_id
  name       = "Bypass — public (everyone)"
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

# dev.nathanbaxter.com — Astro dev server, Access-gated to Nathan
# only. Not in the pod_haus_service module because the hostname is on
# the nathanbaxter.com zone, not pod.haus. Inline, same shape as the
# Pine Lake apps below.
resource "cloudflare_zero_trust_access_application" "nathanbaxter_dev" {
  account_id           = var.account_id
  name                 = "nathanbaxter dev"
  type                 = "self_hosted"
  domain               = "dev.nathanbaxter.com"
  self_hosted_domains  = ["dev.nathanbaxter.com"]
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

# Home Assistant, Syncthing, Torrents, Paperless, UniFi → moved to
# module.* in services_pod_haus.tf. Their per-app "Family" / "Nathan"
# policies (home_assistant_family, syncthing_nathan, torrents_family,
# paperless_family) are now replaced by the shared
# pod_haus_family_allow / nathan reusable policies via the module's
# default chain (or explicit override) — CF garbage-collects the
# orphan per-app policies once nothing references them.

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
# Special-case Applications (not via the per-service module)
# ============================================================================

# Komodo webhook bypass.
# Komodo's per-resource webhook listeners all live under
# /listener/github/... (e.g. /listener/github/stack/<name>/deploy —
# see github.tf). Access path matching is prefix-based and a more
# specific app overrides the *.pod.haus wildcard, so scoping this
# bypass to the /listener/github prefix covers every per-stack
# listener URL while leaving the rest of komodo.pod.haus gated.
# Komodo validates the HMAC itself, so an open bypass here is safe.
resource "cloudflare_zero_trust_access_application" "komodo_webhook" {
  account_id           = var.account_id
  name                 = "Komodo webhook (bypass)"
  type                 = "self_hosted"
  domain               = "komodo.pod.haus/listener/github"
  self_hosted_domains  = ["komodo.pod.haus/listener/github"]
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
