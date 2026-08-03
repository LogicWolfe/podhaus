# Per-site Umami tracker names stay on Cloudflare's HTTP proxy. Caddy exposes
# only /script.js and /api/send; dashboard access uses stats.pod.haus through
# Pomerium.
resource "cloudflare_dns_record" "stats_nathanbaxter_com" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "stats.nathanbaxter.com"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

resource "cloudflare_dns_record" "stats_indigopod_au" {
  zone_id = local.zones["indigopod.au"]
  name    = "stats.indigopod.au"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

resource "cloudflare_dns_record" "stats_skycroeser_net" {
  zone_id = local.zones["skycroeser.net"]
  name    = "stats.skycroeser.net"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}
