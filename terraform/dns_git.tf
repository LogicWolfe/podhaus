# git.pod.haus is Forgejo's single HTTPS + SSH hostname. Cloudflare is
# authoritative DNS only. HTTPS reaches Pomerium and port 22 reaches the
# dedicated Forgejo rathole listener on Numbat's application address.
resource "cloudflare_dns_record" "git_a" {
  zone_id = local.zones["pod.haus"]
  name    = "git.pod.haus"
  type    = "A"
  content = local.numbat_application_ipv4
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
  # Cloudflare normalizes this optional block away after create. Match
  # storage.pod.haus and ignore that cosmetic provider/API round-trip.
  lifecycle {
    ignore_changes = [settings]
  }
}
