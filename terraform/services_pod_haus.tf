# DNS for Pomerium-protected pod.haus services. Pomerium and Caddy own the
# route policy; Terraform only publishes each name to the correct Numbat role.
locals {
  # UniFi reservations still need both physical Kangaroo addresses.
  kangaroo_ip_1g  = "10.0.0.232"
  kangaroo_ip_10g = "10.0.0.25"

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

# Preserve the existing DNS records while retiring the old module's Access and
# Tunnel responsibilities. Remove these blocks after the first apply.
moved {
  from = module.backup.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["backup"]
}
moved {
  from = module.bugsink.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["bugs"]
}
moved {
  from = module.docs.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["docs"]
}
moved {
  from = module.fenwick.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["fenwick"]
}
moved {
  from = module.gatus.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["gatus"]
}
moved {
  from = module.home_assistant.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["home"]
}
moved {
  from = module.kangaroo.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["kangaroo"]
}
moved {
  from = module.kangaroo_backup.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["kangaroo-backup"]
}
moved {
  from = module.komodo.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["komodo"]
}
moved {
  from = module.minio.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["minio"]
}
moved {
  from = module.music.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["music"]
}
moved {
  from = module.paperless.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["paperless"]
}
moved {
  from = module.plex.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["plex"]
}
moved {
  from = module.stats.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["stats"]
}
moved {
  from = module.syncthing.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["sync"]
}
moved {
  from = module.torrents.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["torrent"]
}
moved {
  from = module.watch.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["watch"]
}
moved {
  from = module.pocket_id.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["id"]
}
moved {
  from = module.unifi.cloudflare_dns_record.this
  to   = cloudflare_dns_record.pod_haus_service["unifi"]
}
