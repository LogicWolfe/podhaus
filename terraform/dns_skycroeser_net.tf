# skycroeser.net — Sky Croeser's academic site, migrated off WordPress.com
# to the self-hosted Publii static site served from the skycroeser-net
# MinIO bucket through Numbat and Caddy. Same serving shape as
# nathanbaxter.com's public website records.
#
# PROXIED (orange-cloud): the rendered site is plain static HTTP with no
# SigV4, so Cloudflare's proxy (TLS, cache, DDoS) is correct. No Access
# app — it's a public site. www → apex is a 301 handled in the Caddyfile
# (its own www.skycroeser.net site block).

resource "cloudflare_zone_setting" "skycroeser_net_ssl" {
  zone_id    = local.zones["skycroeser.net"]
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_dns_record" "skycroeser_net_apex_web" {
  zone_id = local.zones["skycroeser.net"]
  name    = "skycroeser.net"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

resource "cloudflare_dns_record" "skycroeser_net_www_web" {
  zone_id = local.zones["skycroeser.net"]
  name    = "www.skycroeser.net"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}
