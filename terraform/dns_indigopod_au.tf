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

resource "cloudflare_dns_record" "pets_indigopod" {
  zone_id = local.zones["indigopod.au"]
  name    = "pets.indigopod.au"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}
