# logicaldecay.net — Google Workspace email only.

resource "cloudflare_dns_record" "logicaldecay_net_mx" {
  for_each = {
    "aspmx.l.google.com"      = 10
    "alt1.aspmx.l.google.com" = 20
    "alt2.aspmx.l.google.com" = 20
    "aspmx2.googlemail.com"   = 30
    "aspmx3.googlemail.com"   = 30
    "aspmx4.googlemail.com"   = 30
    "aspmx5.googlemail.com"   = 30
  }
  zone_id  = local.zones["logicaldecay.net"]
  name     = "logicaldecay.net"
  type     = "MX"
  content  = each.key
  priority = each.value
  ttl      = 300
}

resource "cloudflare_dns_record" "logicaldecay_net_spf" {
  zone_id = local.zones["logicaldecay.net"]
  name    = "logicaldecay.net"
  type    = "TXT"
  content = "\"v=spf1 a include:_spf.google.com ~all\""
  ttl     = 300
}
