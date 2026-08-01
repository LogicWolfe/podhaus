# storage.pod.haus — the public MinIO S3 endpoint. DNS-only
# (grey-cloud): Cloudflare is authoritative DNS but NEVER in the data
# path (its HTTP proxy mangles the SigV4-signed Accept-Encoding header
# and its single-level Universal SSL cert can't cover Publii's
# virtual-host buckets). Traffic now goes: client → this A record
# (kookaburra relay reserved IP) → rathole reverse tunnel → Caddy on
# bilby (own LE *.storage.pod.haus wildcard) → MinIO. LAN clients hit
# Caddy directly via the split-horizon record
# (dns_unifi_split_horizon.tf). See docs/hosts.html#kookaburra.

# Kookaburra reserved IP from the relay's resource (intra-root after
# the foundation consolidation; was a terraform_remote_state cross-
# root read pre-consolidation). cloudflare-ddns is retired for this
# name; the IP is static (DigitalOcean Reserved IP) and survives
# droplet rebuilds. `settings` stays ignored because past DDNS API
# writes normalized it away and un-ignoring it would show perpetual
# cosmetic drift.
resource "cloudflare_dns_record" "storage_a" {
  zone_id = local.zones["pod.haus"]
  name    = "storage.pod.haus"
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
