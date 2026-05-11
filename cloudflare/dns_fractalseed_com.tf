# fractalseed.com — Fastmail-hosted mailbox.

resource "cloudflare_dns_record" "fractalseed_com_dkim" {
  for_each = toset(["fm1", "fm2", "fm3"])
  zone_id  = local.zones["fractalseed.com"]
  name     = "${each.key}._domainkey.fractalseed.com"
  type     = "CNAME"
  content  = "${each.key}.fractalseed.com.dkim.fmhosted.com"
  proxied  = false
  ttl      = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_dns_record" "fractalseed_com_mx" {
  for_each = {
    "10" = "in1-smtp.messagingengine.com"
    "20" = "in2-smtp.messagingengine.com"
  }
  zone_id  = local.zones["fractalseed.com"]
  name     = "fractalseed.com"
  type     = "MX"
  content  = each.value
  priority = tonumber(each.key)
  ttl      = 300
}

resource "cloudflare_dns_record" "fractalseed_com_spf" {
  zone_id = local.zones["fractalseed.com"]
  name    = "fractalseed.com"
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ?all\""
  ttl     = 300
}
