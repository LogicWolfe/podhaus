# indigopod.au — public host for the pets pet simulator.
# Zone is on Cloudflare (zone id in variables.tf locals.zones).
#
# pets.indigopod.au is intentionally PUBLIC: there is NO Cloudflare
# Access application gating it (her friends authenticate to the game
# itself via the in-app edit password / play sessions, not at the edge).
# Same "public site, no Access app" pattern as nathanbaxter.com.

resource "cloudflare_zone_setting" "indigopod_au_ssl" {
  zone_id    = local.zones["indigopod.au"]
  setting_id = "ssl"
  value      = "strict"
}

# doggos.indigopod.au — Indigo's Blocs site, served from the doggos-indigo
# MinIO bucket through Numbat's relay and Caddy :4444 (the yiayia posture).
# DNS-only, no CDN: it is not in the caching contract (docs/caching.md).
resource "cloudflare_dns_record" "doggos_indigopod" {
  zone_id = local.zones["indigopod.au"]
  name    = "doggos.indigopod.au"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_dns_record" "pets_indigopod" {
  zone_id = local.zones["indigopod.au"]
  name    = "pets.indigopod.au"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

# Fastmail for indigo@indigopod.au: the three DKIM CNAMEs, both exchangers,
# and a neutral SPF record. The mailbox itself is a Fastmail-side rename of
# her pod.haus user, which keeps the old address as an alias.
#
# The exchangers are the us1/us2 hostnames Fastmail's own setup screen gives
# for a domain added now. pod.haus and nathanbaxter.com still name the older
# in1/in2 pair, which Fastmail continues to accept; do not align the zones on
# one pair without checking what Fastmail asks for each domain.
locals {
  indigopod_au_dkim_selectors = toset(["fm1", "fm2", "fm3"])
}

resource "cloudflare_dns_record" "indigopod_au_dkim" {
  for_each = local.indigopod_au_dkim_selectors
  zone_id  = local.zones["indigopod.au"]
  name     = "${each.key}._domainkey.indigopod.au"
  type     = "CNAME"
  content  = "${each.key}.indigopod.au.dkim.fmhosted.com"
  proxied  = false
  ttl      = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_dns_record" "indigopod_au_mx" {
  for_each = {
    "10" = "us1-smtp.messagingengine.com"
    "20" = "us2-smtp.messagingengine.com"
  }
  zone_id  = local.zones["indigopod.au"]
  name     = "indigopod.au"
  type     = "MX"
  content  = each.value
  priority = tonumber(each.key)
  ttl      = 300
}

resource "cloudflare_dns_record" "indigopod_au_txt_spf" {
  zone_id = local.zones["indigopod.au"]
  name    = "indigopod.au"
  type    = "TXT"
  content = "\"v=spf1 include:spf.messagingengine.com ?all\""
  ttl     = 300
}

# Monitoring-only DMARC, the record Fastmail's own setup asks for. It cannot
# fail delivery at p=none; tightening it is a later decision.
resource "cloudflare_dns_record" "indigopod_au_txt_dmarc" {
  zone_id = local.zones["indigopod.au"]
  name    = "_dmarc.indigopod.au"
  type    = "TXT"
  content = "\"v=DMARC1; p=none;\""
  ttl     = 300
}
