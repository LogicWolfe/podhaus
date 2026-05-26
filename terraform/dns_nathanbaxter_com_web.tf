# nathanbaxter.com PUBLIC WEBSITE records — static site served from
# the nathanbaxter-com MinIO bucket via the pod_haus Cloudflare Tunnel
# → Caddy. Separate file from dns_nathanbaxter_com.tf so the mail
# records (Fastmail MX/DKIM/SRV, Postmark) are never touched.
#
# These are PROXIED (orange-cloud): unlike the S3 *API*
# (storage.pod.haus, grey-cloud), the rendered website is plain static
# HTTP with no SigV4 — Cloudflare's proxy (TLS, cache, DDoS) is
# correct and desirable here. No Access app: it's a public site.

resource "cloudflare_dns_record" "nathanbaxter_com_apex_web" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "nathanbaxter.com"
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

resource "cloudflare_dns_record" "nathanbaxter_com_www_web" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "www.nathanbaxter.com"
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
