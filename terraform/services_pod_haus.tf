# DNS for Pomerium-protected pod.haus services. Pomerium and Caddy own the
# route policy; Terraform only publishes each name to the correct Numbat role.
locals {
  # UniFi reservations still need both physical Kangaroo addresses.
  kangaroo_ip_1g  = "10.0.0.232"
  kangaroo_ip_10g = "10.0.0.25"
  # The Windows desktop hosting the fractal WSL guest; forwards only :22
  # into it. Reserved so the split-horizon fractal.pod.haus record and
  # every ssh config pointing at it stay truthful.
  fractal_windows_ip = "10.0.0.70"
  # The ESP32 bridging the burrow Turn Touch. Reserved because Alloy scrapes
  # its /metrics by IP — Docker's resolver has no mDNS, so the .local name is
  # unreachable from the container and a DHCP drift would end the scrape
  # silently.
  turn_touch_burrow_ip = "10.0.0.238"
  # The Pi Zero bridging the Flic buttons. Reserved because Home Assistant's
  # flic integration dials flicd at a fixed host:port and HA runs in a
  # container with no mDNS, so pizero.local is unreachable from it. A DHCP
  # drift would silently stop every button working.
  pizero_ip = "10.0.0.77"
  # The ESP32 switching the grasshopper LED strip. Reserved for the same
  # reason as the Turn Touch: Alloy scrapes its /metrics by IP.
  led_strip_grasshopper_ip = "10.0.0.44"

  pod_haus_service_dns = {
    backup          = local.numbat_application_ipv4
    bugs            = local.numbat_application_ipv4
    docs            = local.numbat_application_ipv4
    fenwick         = local.numbat_application_ipv4
    gatus           = local.numbat_application_ipv4
    home            = local.numbat_application_ipv4
    kangaroo        = local.numbat_application_ipv4
    kangaroo-backup = local.numbat_application_ipv4
    komodo          = local.numbat_application_ipv4
    minio           = local.numbat_application_ipv4
    music           = local.numbat_application_ipv4
    paperless       = local.numbat_application_ipv4
    plex            = local.numbat_application_ipv4
    stats           = local.numbat_application_ipv4
    sync            = local.numbat_application_ipv4
    torrent         = local.numbat_application_ipv4
    watch           = local.numbat_application_ipv4
    id              = local.numbat_relay_ipv4
    unifi           = local.numbat_relay_ipv4
  }
}

resource "cloudflare_dns_record" "pod_haus_service" {
  for_each = local.pod_haus_service_dns

  zone_id = local.zones["pod.haus"]
  name    = "${each.key}.pod.haus"
  type    = "A"
  content = each.value
  proxied = false
  ttl     = 300
}
