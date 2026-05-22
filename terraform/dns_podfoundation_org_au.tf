# podfoundation.org.au — Cloudflare email routing inbound, DMARC at p=none.

resource "cloudflare_dns_record" "podfoundation_org_au_mx" {
  for_each = {
    "amir.mx.cloudflare.net"  = 39
    "linda.mx.cloudflare.net" = 63
    "isaac.mx.cloudflare.net" = 76
  }
  zone_id  = local.zones["podfoundation.org.au"]
  name     = "podfoundation.org.au"
  type     = "MX"
  content  = each.key
  priority = each.value
  ttl      = 300
}

resource "cloudflare_dns_record" "podfoundation_org_au_spf" {
  zone_id = local.zones["podfoundation.org.au"]
  name    = "podfoundation.org.au"
  type    = "TXT"
  content = "\"v=spf1 include:_spf.mx.cloudflare.net ~all\""
  ttl     = 300
}

resource "cloudflare_dns_record" "podfoundation_org_au_dmarc" {
  zone_id = local.zones["podfoundation.org.au"]
  name    = "_dmarc.podfoundation.org.au"
  type    = "TXT"
  content = "\"v=DMARC1; p=none; rua=mailto:nathan@podfoundation.org.au\""
  ttl     = 300
}
