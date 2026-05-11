# nathanbaxter.com — Fastmail mail + web/dav, Postmark transactional,
# Keybase verification. Most complex zone — Fastmail's caldav/carddav
# SRV records need data{} blocks (provider v5 schema).

# DKIM CNAMEs for Fastmail.
resource "cloudflare_dns_record" "nathanbaxter_com_dkim" {
  for_each = toset(["fm1", "fm2", "fm3"])
  zone_id  = local.zones["nathanbaxter.com"]
  name     = "${each.key}._domainkey.nathanbaxter.com"
  type     = "CNAME"
  content  = "${each.key}.nathanbaxter.com.dkim.fmhosted.com"
  proxied  = false
  ttl      = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

# Fastmail web app + DKIM-rotation CNAME apex helper.
resource "cloudflare_dns_record" "nathanbaxter_com_mail" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "mail.nathanbaxter.com"
  type    = "CNAME"
  content = "app.fastmail.com"
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

# Postmark bounce hostname.
resource "cloudflare_dns_record" "nathanbaxter_com_pm_bounces" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "pm-bounces.nathanbaxter.com"
  type    = "CNAME"
  content = "pm.mtasv.net"
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

# MX records — Fastmail primary + secondary, at apex, www, and the
# catch-all *.nathanbaxter.com.
locals {
  nathanbaxter_com_mail_names = ["nathanbaxter.com", "*.nathanbaxter.com", "www.nathanbaxter.com"]
}

resource "cloudflare_dns_record" "nathanbaxter_com_mx" {
  for_each = {
    for pair in flatten([
      for name in local.nathanbaxter_com_mail_names : [
        { key = "${name}|10", name = name, prio = 10, host = "in1-smtp.messagingengine.com" },
        { key = "${name}|20", name = name, prio = 20, host = "in2-smtp.messagingengine.com" },
      ]
    ]) : pair.key => pair
  }
  zone_id  = local.zones["nathanbaxter.com"]
  name     = each.value.name
  type     = "MX"
  content  = each.value.host
  priority = each.value.prio
  ttl      = 300
}

# Fastmail web service SRVs. v5 provider requires the `data` block —
# `content` cannot be set alongside it. priority on the SRV resource
# itself is the SRV "priority" field; CF API returns it both top-level
# and inside data, but the provider only accepts it top-level.
# The provider returns top-level priority for SRV records (derived from
# data.priority) and complains about drift if we omit it — so set both.
# `content` is purely derived and must not be set.

resource "cloudflare_dns_record" "nathanbaxter_com_srv_caldavs" {
  zone_id  = local.zones["nathanbaxter.com"]
  name     = "_caldavs._tcp.nathanbaxter.com"
  type     = "SRV"
  ttl      = 300
  priority = 0
  data = {
    priority = 0
    weight   = 1
    port     = 443
    target   = "caldav.fastmail.com"
  }
}

resource "cloudflare_dns_record" "nathanbaxter_com_srv_carddavs" {
  zone_id  = local.zones["nathanbaxter.com"]
  name     = "_carddavs._tcp.nathanbaxter.com"
  type     = "SRV"
  ttl      = 300
  priority = 0
  data = {
    priority = 0
    weight   = 1
    port     = 443
    target   = "carddav.fastmail.com"
  }
}

resource "cloudflare_dns_record" "nathanbaxter_com_srv_imaps" {
  zone_id  = local.zones["nathanbaxter.com"]
  name     = "_imaps._tcp.nathanbaxter.com"
  type     = "SRV"
  ttl      = 300
  priority = 0
  data = {
    priority = 0
    weight   = 1
    port     = 993
    target   = "imap.fastmail.com"
  }
}

resource "cloudflare_dns_record" "nathanbaxter_com_srv_pop3s" {
  zone_id  = local.zones["nathanbaxter.com"]
  name     = "_pop3s._tcp.nathanbaxter.com"
  type     = "SRV"
  ttl      = 300
  priority = 10
  data = {
    priority = 10
    weight   = 1
    port     = 995
    target   = "pop.fastmail.com"
  }
}

resource "cloudflare_dns_record" "nathanbaxter_com_srv_submission" {
  zone_id  = local.zones["nathanbaxter.com"]
  name     = "_submission._tcp.nathanbaxter.com"
  type     = "SRV"
  ttl      = 300
  priority = 0
  data = {
    priority = 0
    weight   = 1
    port     = 587
    target   = "smtp.fastmail.com"
  }
}

# Postmark DKIM. Selector encodes issuance date.
resource "cloudflare_dns_record" "nathanbaxter_com_postmark_dkim" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "20251019030332pm._domainkey.nathanbaxter.com"
  type    = "TXT"
  content = "\"k=rsa;p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDYtsXWV3F5hNjZtbIHesrQ40jJ9fYiX/te3iiDt+6+dGHwjroZQDwGRg9hcEjRX/Ev1UTecR32/14Ie7zoD35OwiZ8c0/V5ojaB2CHtaWVHkzwINwKTCCcOOBbezHFsUvk7JPE7Il5U0weRbcLEcYOxyM1oEXxTrA+wlKS13JkaQIDAQAB\""
  ttl     = 300
}

# Keybase site verification.
resource "cloudflare_dns_record" "nathanbaxter_com_keybase" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "nathanbaxter.com"
  type    = "TXT"
  content = "\"keybase-site-verification=PYg39KGImTNyG3xYnl4VUNhzg51qNFmDhZyBDwLKO0A\""
  ttl     = 300
}

# SPF.
resource "cloudflare_dns_record" "nathanbaxter_com_spf" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "nathanbaxter.com"
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ~all\""
  ttl     = 300
}
