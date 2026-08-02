locals {
  public_site_cache = {
    "nathanbaxter.com" = {
      zone_id    = local.zones["nathanbaxter.com"]
      expression = "(http.request.method in {\"GET\" \"HEAD\"} and http.host eq \"nathanbaxter.com\")"
    }
    "pets.indigopod.au" = {
      zone_id    = local.zones["indigopod.au"]
      expression = "(http.request.method in {\"GET\" \"HEAD\"} and http.host eq \"pets.indigopod.au\")"
    }
    "skycroeser.net" = {
      zone_id    = local.zones["skycroeser.net"]
      expression = "(http.request.method in {\"GET\" \"HEAD\"} and http.host eq \"skycroeser.net\")"
    }
  }
}

resource "cloudflare_ruleset" "public_site_cache" {
  for_each = local.public_site_cache

  zone_id = each.value.zone_id
  name    = "Origin-directed cache for ${each.key}"
  kind    = "zone"
  phase   = "http_request_cache_settings"

  rules = [{
    ref         = "origin_directed_public_site_cache"
    description = "Cache only when the origin sends explicit CDN cache policy"
    expression  = each.value.expression
    action      = "set_cache_settings"
    enabled     = true
    action_parameters = {
      cache = true
      edge_ttl = {
        mode = "bypass_by_default"
      }
      browser_ttl = {
        mode = "respect_origin"
      }
    }
  }]
}

resource "cloudflare_tiered_cache" "public_site_cache" {
  for_each = local.public_site_cache

  zone_id = each.value.zone_id
  value   = "on"
}

resource "cloudflare_argo_tiered_caching" "public_site_cache" {
  for_each = local.public_site_cache

  zone_id = each.value.zone_id
  value   = "on"
}

# The public site origins accept TLS only from Cloudflare's shared
# Authenticated Origin Pull certificate. Direct-to-Numbat requests cannot
# bypass the CDN's cache and edge controls.
resource "cloudflare_authenticated_origin_pulls_settings" "public_site_cache" {
  for_each = local.public_site_cache

  zone_id = each.value.zone_id
  enabled = true
}
