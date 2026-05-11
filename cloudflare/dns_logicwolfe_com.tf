# logicwolfe.com — apex redirect to nathanbaxter.com (single CNAME).
# CF flattens CNAME at apex automatically; this is documented in
# `dns/dnsconfig.js` as the equivalent ALIAS construct.

resource "cloudflare_dns_record" "logicwolfe_com_apex_alias" {
  zone_id = local.zones["logicwolfe.com"]
  name    = "logicwolfe.com"
  type    = "CNAME"
  content = "nathanbaxter.com"
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}
