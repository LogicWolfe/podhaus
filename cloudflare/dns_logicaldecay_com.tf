# logicaldecay.com — Google Workspace email only (XMPP SRV removed
# earlier). No web — apex is unrouted.

resource "cloudflare_dns_record" "logicaldecay_com_mx" {
  for_each = {
    "aspmx.l.google.com"      = 1
    "alt1.aspmx.l.google.com" = 5
    "alt2.aspmx.l.google.com" = 5
    "aspmx2.googlemail.com"   = 10
    "aspmx3.googlemail.com"   = 10
  }
  zone_id  = local.zones["logicaldecay.com"]
  name     = "logicaldecay.com"
  type     = "MX"
  content  = each.key
  priority = each.value
  ttl      = 300
}

resource "cloudflare_dns_record" "logicaldecay_com_spf" {
  zone_id = local.zones["logicaldecay.com"]
  name    = "logicaldecay.com"
  type    = "TXT"
  content = "\"v=spf1 a include:_spf.google.com ~all\""
  ttl     = 300
}
