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
