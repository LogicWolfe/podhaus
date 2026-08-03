# pouch.pod.haus is the public endpoint for the Pouch-backed MinIO instance
# on kangaroo. Cloudflare provides DNS only. Raw :443 reaches Numbat, crosses
# the rathole service to bilby's Caddy, then crosses the LAN to kangaroo.
# SigV4 remains the auth boundary.
resource "cloudflare_dns_record" "pouch_a" {
  zone_id = local.zones["pod.haus"]
  name    = "pouch.pod.haus"
  type    = "A"
  content = local.numbat_relay_ipv4
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
  lifecycle {
    ignore_changes = [settings]
  }
}
