# skycroeser.net — Sky Croeser's academic site, migrated off WordPress.com
# to the self-hosted Publii static site served from the skycroeser-net
# MinIO bucket via the pod_haus Cloudflare Tunnel → Caddy (caddy/Caddyfile
# host-matches skycroeser.net alongside sky.pod.haus). Same serving shape
# as nathanbaxter.com's public website records.
#
# PROXIED (orange-cloud): the rendered site is plain static HTTP with no
# SigV4, so Cloudflare's proxy (TLS, cache, DDoS) is correct. No Access
# app — it's a public site. www → apex is a 301 handled in the Caddyfile
# (its own www.skycroeser.net site block), so www is still a proxied CNAME
# to the tunnel to reach Caddy.

resource "cloudflare_dns_record" "skycroeser_net_apex_web" {
  zone_id = local.zones["skycroeser.net"]
  name    = "skycroeser.net"
  type    = "CNAME"
  content = local.tunnels.pod_haus # Cloudflare flattens the apex CNAME
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}

resource "cloudflare_dns_record" "skycroeser_net_www_web" {
  zone_id = local.zones["skycroeser.net"]
  name    = "www.skycroeser.net"
  type    = "CNAME"
  content = local.tunnels.pod_haus
  proxied = true
  ttl     = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}
