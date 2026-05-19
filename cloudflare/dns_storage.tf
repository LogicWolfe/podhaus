# storage.pod.haus — the public MinIO S3 endpoint. DNS-only
# (grey-cloud): Cloudflare is authoritative DNS but NEVER in the data
# path (its HTTP proxy mangles the SigV4-signed Accept-Encoding header
# and its single-level Universal SSL cert can't cover Publii's
# virtual-host buckets). Traffic goes: client → this A record (home
# WAN IP) → UniFi port-forward (unifi_port_forward.tf) → Caddy on
# bilby (own LE *.storage.pod.haus wildcard) → MinIO. See
# docs/plans/minio-public-caddy.md.

# The A record's VALUE is owned by the cloudflare-ddns stack (the WAN
# IP is contractually static today but DDNS removes the hidden
# dependency — esp. across a house move). Terraform owns the record's
# existence/type; DDNS owns its content. `ignore_changes` makes that
# boundary explicit so `tf apply` never reverts a DDNS update.
resource "cloudflare_dns_record" "storage_a" {
  zone_id = local.zones["pod.haus"]
  name    = "storage.pod.haus"
  type    = "A"
  content = "144.6.147.203" # bootstrap value; thereafter DDNS-managed
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
  # DDNS (cloudflare-ddns) owns this record's live value. Its API
  # writes also normalize `settings` away, so ignore both — TF owns
  # the record's existence/name/type, DDNS owns the rest. Without
  # ignoring `settings` every plan perpetually shows in-place drift.
  lifecycle {
    ignore_changes = [content, settings]
  }
}

# Virtual-host bucket names (Publii / aws-sdk-js v3):
# <bucket>.storage.pod.haus → storage.pod.haus → WAN IP.
resource "cloudflare_dns_record" "storage_wildcard" {
  zone_id = local.zones["pod.haus"]
  name    = "*.storage.pod.haus"
  type    = "CNAME"
  content = "storage.pod.haus"
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
}
