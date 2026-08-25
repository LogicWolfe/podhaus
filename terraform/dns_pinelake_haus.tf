# Pinelake is off-LAN and reaches the fleet by dialing out to Numbat. Its
# public names therefore use the same DNS-only BinaryLane application address
# as the protected pod.haus estate.

resource "cloudflare_dns_record" "pinelake_haus_home" {
  zone_id = local.zones["pinelake.haus"]
  name    = "home.pinelake.haus"
  type    = "A"
  content = local.numbat_application_ipv4
  proxied = false
  ttl     = 300
}

resource "cloudflare_dns_record" "pinelake_haus_pomerium" {
  for_each = toset(["sync", "torrent"])
  zone_id  = local.zones["pinelake.haus"]
  name     = "${each.key}.pinelake.haus"
  type     = "A"
  content  = local.numbat_application_ipv4
  proxied  = false
  ttl      = 300
}
