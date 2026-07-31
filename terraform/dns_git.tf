# git.pod.haus is Forgejo's single HTTPS + SSH hostname. Cloudflare is
# authoritative DNS only: clients connect to kookaburra's stable
# Reserved IP. Rathole forwards anchor-IP :22 to Forgejo's embedded SSH
# server and public :443 to bilby's Caddy, which terminates TLS and
# proxies the web UI to Forgejo.
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
  # Cloudflare normalizes this optional block away after create. Match
  # storage.pod.haus and ignore that cosmetic provider/API round-trip.
  lifecycle {
    ignore_changes = [settings]
  }
}
