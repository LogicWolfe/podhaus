terraform {
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

locals {
  fqdn = "${var.hostname}.pod.haus"

  # If the caller didn't override the policy chain, default to the
  # locked-by-default pair: Homelab service-token bypass (precedence 1)
  # so automation works, Family allow (precedence 2) so the household
  # can log in. Both are referenced by ID — the actual policy resources
  # live in cloudflare/access.tf as shared reusable policies.
  effective_policy_ids = coalesce(
    var.access_policy_ids,
    compact([var.default_bypass_policy_id, var.default_allow_policy_id]),
  )

  policies = [
    for i, pid in local.effective_policy_ids : {
      precedence = i + 1
      id         = pid
    }
  ]

  # Structured ingress rule consumed by cloudflare/tunnel.tf, which
  # concatenates rules from every module instance into the tunnel's
  # config.ingress list. Always populate every key so the per-entry
  # object types unify cleanly under `concat()`.
  ingress_rule = {
    hostname       = local.fqdn
    service        = var.backend
    path           = var.ingress_path
    origin_request = var.origin_request
  }
}

resource "cloudflare_dns_record" "this" {
  zone_id = var.zone_id
  name    = local.fqdn
  type    = "CNAME"
  content = var.tunnel_target
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_zero_trust_access_application" "this" {
  account_id       = var.account_id
  name             = var.hostname
  type             = var.app_type
  session_duration = var.session_duration
  tags             = var.tags

  # `destinations` supersedes the deprecated `self_hosted_domains`. Each
  # service is single-host by default; callers can extend later if a
  # service ever needs to gate multiple URIs.
  destinations = [
    {
      type = "public"
      uri  = var.ingress_path == null ? local.fqdn : "${local.fqdn}${var.ingress_path}"
    },
  ]

  # Standard settings to match the rest of the fleet. Setting these
  # explicitly avoids provider-default drift on every refresh.
  auto_redirect_to_identity  = false
  enable_binding_cookie      = false
  options_preflight_bypass   = false
  app_launcher_visible       = var.app_launcher_visible
  http_only_cookie_attribute = true

  policies = local.policies
}
