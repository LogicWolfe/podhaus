# elusive.email — Fastmail-hosted mailbox.

resource "cloudflare_dns_record" "elusive_email_dkim" {
  for_each = toset(["fm1", "fm2", "fm3"])
  zone_id  = local.zones["elusive.email"]
  name     = "${each.key}._domainkey.elusive.email"
  type     = "CNAME"
  content  = "${each.key}.elusive.email.dkim.fmhosted.com"
  proxied  = false
  ttl      = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_dns_record" "elusive_email_mx" {
  for_each = {
    "10" = "in1-smtp.messagingengine.com"
    "20" = "in2-smtp.messagingengine.com"
  }
  zone_id  = local.zones["elusive.email"]
  name     = "elusive.email"
  type     = "MX"
  content  = each.value
  priority = tonumber(each.key)
  ttl      = 300
}

resource "cloudflare_dns_record" "elusive_email_spf" {
  zone_id = local.zones["elusive.email"]
  name    = "elusive.email"
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ?all\""
  ttl     = 300
}
