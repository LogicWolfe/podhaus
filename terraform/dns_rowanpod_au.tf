# rowanpod.au — Rowan's domain. Mail only for now, the same Fastmail shape as
# indigopod.au: three DKIM CNAMEs, both exchangers, a neutral SPF record and a
# monitoring-only DMARC record. No web records, no SSL zone setting; those
# arrive with a site, as they did for Indigo's.
#
# Fastmail names the us1/us2 exchangers for a domain added now. The older
# zones here carry the in1/in2 pair, which Fastmail still accepts; check what
# Fastmail asks for a given domain rather than aligning the zones by hand.
#
# The mailbox itself is Fastmail-side: add the domain, then give Rowan an
# address on it.

resource "cloudflare_dns_record" "rowanpod_au_dkim" {
  for_each = toset(["fm1", "fm2", "fm3"])
  zone_id  = local.zones["rowanpod.au"]
  name     = "${each.key}._domainkey.rowanpod.au"
  type     = "CNAME"
  content  = "${each.key}.rowanpod.au.dkim.fmhosted.com"
  proxied  = false
  ttl      = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_dns_record" "rowanpod_au_mx" {
  for_each = {
    "10" = "us1-smtp.messagingengine.com"
    "20" = "us2-smtp.messagingengine.com"
  }
  zone_id  = local.zones["rowanpod.au"]
  name     = "rowanpod.au"
  type     = "MX"
  content  = each.value
  priority = tonumber(each.key)
  ttl      = 300
}

resource "cloudflare_dns_record" "rowanpod_au_txt_spf" {
  zone_id = local.zones["rowanpod.au"]
  name    = "rowanpod.au"
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ?all\""
  ttl     = 300
}

resource "cloudflare_dns_record" "rowanpod_au_txt_dmarc" {
  zone_id = local.zones["rowanpod.au"]
  name    = "_dmarc.rowanpod.au"
  type    = "TXT"
  content = "\"v=DMARC1; p=none;\""
  ttl     = 300
}
