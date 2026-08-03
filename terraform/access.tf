# Cloudflare Access remains only for the existing Pine Lake services. Podhaus
# browser and machine access is owned by Pomerium.

data "onepassword_vault" "homelab" {
  name = "Homelab"
}

resource "cloudflare_zero_trust_access_group" "family" {
  account_id = var.account_id
  name       = "Family"

  include = [
    { email_domain = { domain = "nathanbaxter.com" } },
    { email_domain = { domain = "pod.haus" } },
    { email = { email = "scroeser@gmail.com" } },
  ]
}

resource "cloudflare_zero_trust_access_policy" "nathan" {
  account_id = var.account_id
  name       = "Nathan"
  decision   = "allow"
  include    = [{ email = { email = "nathan@nathanbaxter.com" } }]
}

resource "cloudflare_zero_trust_access_application" "pine_lake_ssh" {
  account_id       = var.account_id
  name             = "Pine Lake SSH"
  type             = "ssh"
  domain           = "home.pinelake.haus"
  destinations     = [{ type = "public", uri = "home.pinelake.haus" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  app_launcher_visible       = true
  http_only_cookie_attribute = false
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
  ]
}

resource "cloudflare_zero_trust_access_application" "pine_lake_torrent" {
  account_id       = var.account_id
  name             = "Pine Lake Torrent"
  type             = "self_hosted"
  domain           = "torrent.pinelake.haus"
  destinations     = [{ type = "public", uri = "torrent.pinelake.haus" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = true
  http_only_cookie_attribute = false
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
  ]
}

resource "cloudflare_zero_trust_access_application" "pine_lake_syncthing" {
  account_id       = var.account_id
  name             = "Pine Lake Syncthing"
  type             = "self_hosted"
  domain           = "sync.pinelake.haus"
  destinations     = [{ type = "public", uri = "sync.pinelake.haus" }]
  session_duration = "730h"

  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = true
  app_launcher_visible       = true
  http_only_cookie_attribute = false
  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.nathan.id },
  ]
}

resource "cloudflare_zero_trust_access_application" "app_launcher" {
  account_id       = var.account_id
  name             = "App Launcher"
  type             = "app_launcher"
  session_duration = "24h"

  policies = [
    { precedence = 1, id = cloudflare_zero_trust_access_policy.app_launcher_family.id },
  ]

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

data "onepassword_item" "pocket_id_oidc" {
  vault = data.onepassword_vault.homelab.uuid
  title = "Pocket ID OIDC"
}

resource "cloudflare_zero_trust_access_identity_provider" "pocket_id" {
  account_id = var.account_id
  name       = "Pocket ID"
  type       = "oidc"

  config = {
    client_id     = data.onepassword_item.pocket_id_oidc.section_map["OIDC"].field_map["client id"].value
    client_secret = data.onepassword_item.pocket_id_oidc.section_map["OIDC"].field_map["client secret"].value
    auth_url      = "https://id.pod.haus/authorize"
    token_url     = "https://id.pod.haus/api/oidc/token"
    certs_url     = "https://id.pod.haus/.well-known/jwks.json"
    scopes        = ["openid", "email", "profile"]
    pkce_enabled  = true
  }

  lifecycle {
    ignore_changes = [config.client_secret]
  }
}
