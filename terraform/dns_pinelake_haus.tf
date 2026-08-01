# pinelake.haus tunnel-routed CNAMEs. Pinelake is not on the home LAN,
# so this root does not create split-horizon UniFi records for it.

resource "cloudflare_dns_record" "pinelake_haus_tunnel" {
  for_each = toset(["home", "sync", "torrent"])
  zone_id  = local.zones["pinelake.haus"]
  name     = "${each.key}.pinelake.haus"
  type     = "CNAME"
  content  = local.tunnels.pinelake
  proxied  = true
  ttl      = 1
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}
