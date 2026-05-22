# nathanbaxter.net — apex URI record redirecting to nathanbaxter.com.
# URI is the v5 schema-quirk record type: uses `data { }` (target +
# weight) plus top-level priority, never `content`.

resource "cloudflare_dns_record" "nathanbaxter_net_uri" {
  zone_id  = local.zones["nathanbaxter.net"]
  name     = "nathanbaxter.net"
  type     = "URI"
  ttl      = 1
  priority = 1
  data = {
    weight = 1
    target = "nathanbaxter.com"
  }
}
