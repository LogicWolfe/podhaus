# WAF for the public S3 endpoint (storage.pod.haus).
#
# storage.pod.haus fronts MinIO's :9000, which serves BOTH the S3 API
# and the MinIO admin API on the same port. Two guards:
#   1. firewall_custom — hard-block the /minio/admin/ surface so the
#      admin API is never reachable from the internet even with valid
#      root creds. This is the load-bearing edge control. MinIO S3
#      SigV4 is the auth for everything else.
#   2. cache_settings — bypass cache so signed S3 GET/HEAD responses
#      are never cached/served stale.
#
# No rate-limiting rule: meaningful rate limiting here needs
# response-scoped counting (count only 401/403 so legit bulk Publii
# uploads aren't throttled), which is a paid-plan feature. On Free,
# any per-IP request-count limit either throttles legitimate bulk
# uploads or is too loose to matter — and SigV4 can't be brute-forced,
# so it adds no real protection. Deliberately omitted (not overengineered).
#
# Zone-level custom rules + cache rules are Free-plan features; each
# phase entrypoint is a single zone-kind ruleset. Token needs
# `Zone : WAF : Edit` for the firewall ruleset (NOT legacy "Firewall
# Services") + `Zone : Cache Rules : Edit` for the cache ruleset.
#
# Reference doc (read before editing — schema differs across v5 minors):
#   https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/ruleset

resource "cloudflare_ruleset" "storage_firewall" {
  zone_id     = local.zones["pod.haus"]
  name        = "storage.pod.haus — block admin API"
  kind        = "zone"
  phase       = "http_request_firewall_custom"
  description = "Keep MinIO admin API (same :9000 port) off the internet"

  rules = [
    {
      ref         = "storage_block_minio_admin"
      description = "Block /minio/admin/ on storage.pod.haus"
      expression  = "(http.host eq \"storage.pod.haus\" and starts_with(http.request.uri.path, \"/minio/admin/\"))"
      action      = "block"
    },
  ]
}

resource "cloudflare_ruleset" "storage_cache" {
  zone_id     = local.zones["pod.haus"]
  name        = "storage.pod.haus — cache bypass"
  kind        = "zone"
  phase       = "http_request_cache_settings"
  description = "Never cache signed S3 API responses"

  rules = [
    {
      ref         = "storage_cache_bypass"
      description = "Bypass cache for storage.pod.haus"
      expression  = "(http.host eq \"storage.pod.haus\")"
      action      = "set_cache_settings"

      action_parameters = {
        cache = false
      }
    },
  ]
}
