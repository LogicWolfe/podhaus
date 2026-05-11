# nathanbaxter.org — apex URI record redirecting to nathanbaxter.com.
# See dns_nathanbaxter_net.tf for the URI schema quirk.

resource "cloudflare_dns_record" "nathanbaxter_org_uri" {
  zone_id  = local.zones["nathanbaxter.org"]
  name     = "nathanbaxter.org"
  type     = "URI"
  ttl      = 1
  priority = 1
  data = {
    weight = 1
    target = "nathanbaxter.com"
  }
}
