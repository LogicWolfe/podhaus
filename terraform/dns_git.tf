# git.pod.haus is raw SSH, not an HTTP service. Cloudflare is
# authoritative DNS only: clients connect to kookaburra's stable
# Reserved IP on standard port 22, DigitalOcean maps that to the
# droplet's anchor IPv4, and rathole forwards the TCP stream to
# Forgejo's embedded SSH server on bilby.
resource "cloudflare_dns_record" "git_a" {
  zone_id = local.zones["pod.haus"]
  name    = "git.pod.haus"
  type    = "A"
  content = digitalocean_reserved_ip.kookaburra.ip_address
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}
