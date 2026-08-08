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
