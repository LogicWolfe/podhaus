# nathanbaxter.com PUBLIC WEBSITE records. Cloudflare's CDN reaches the
# Numbat relay, then rathole, Caddy, and the nathanbaxter-com MinIO bucket.
# Separate file from dns_nathanbaxter_com.tf so the mail
# records (Fastmail MX/DKIM/SRV, Postmark) are never touched.
#
# These are PROXIED (orange-cloud): unlike the S3 *API*
# (storage.pod.haus, grey-cloud), the rendered website is plain static
# HTTP with no SigV4 — Cloudflare's proxy (TLS, cache, DDoS) is
# correct and desirable here. No Access app: it's a public site.

# The old Tunnel origin was HTTP, so this zone historically used Flexible.
# Numbat terminates origin TLS with a publicly valid Caddy certificate.
resource "cloudflare_zone_setting" "nathanbaxter_com_ssl" {
  zone_id    = local.zones["nathanbaxter.com"]
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_dns_record" "nathanbaxter_com_apex_web" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "nathanbaxter.com"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}

resource "cloudflare_dns_record" "nathanbaxter_com_www_web" {
  zone_id = local.zones["nathanbaxter.com"]
  name    = "www.nathanbaxter.com"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = true
  ttl     = 1
}
