# UniFi-side LAN DNS — split-horizon overrides for pod.haus hostnames
# that resolve to internal IPs when the requester is on the home
# network. The public CNAMEs (managed in services_pod_haus.tf via the
# Cloudflare tunnel) take precedence over these for off-LAN requests;
# UniFi's resolver is the one that hands these out to LAN clients.
#
# Reference docs:
#   - ubiquiti-community/unifi provider:
#     https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs
#   - unifi_dns_record resource:
#     https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs/resources/dns_record

resource "unifi_dns_record" "unifi_pod_haus" {
  name        = "unifi.pod.haus"
  record_type = "A"
  value       = "10.0.0.1"
  ttl         = 300
  enabled     = true
}

resource "unifi_dns_record" "bilby_pod_haus" {
  name        = "bilby.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = 300
  enabled     = true
}

# storage.pod.haus + per-site Publii vhost names → bilby directly for
# LAN clients (Caddy on the LAN, no WAN/NAT-hairpin/VPN path). UniFi's
# DNS records are per-name (no wildcard), so each Publii bucket vhost
# gets its own split-horizon A record alongside the apex. Off-LAN
# clients (remote, e.g. Sky) use the grey-cloud Cloudflare record →
# WAN port-forward as normal.
resource "unifi_dns_record" "storage_pod_haus" {
  name        = "storage.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = 300
  enabled     = true
}

# Publii uploads to <bucket>.storage.pod.haus (virtual-host). Keep LAN
# publishes off the WAN/hairpin path (was the cause of VPN-MTU TLS
# handshake failures from a home laptop). One per Publii site.
resource "unifi_dns_record" "nathanbaxter_com_storage" {
  name        = "nathanbaxter-com.storage.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = 300
  enabled     = true
}

# Gatus external-path probe — UniFi returns the kookaburra relay
# reserved IP for this *.storage.pod.haus subdomain so the on-bilby
# gatus container (which uses host DNS via UniFi) reaches the relay
# instead of the LAN split-horizon target. The hostname is under
# *.storage.pod.haus so Caddy's wildcard LE cert validates the TLS.
# Source of truth: the relay TF root's reserved_ip output (read via
# terraform_remote_state in remote_state.tf) — no hardcoded IP.
resource "unifi_dns_record" "kookaburra_probe_storage" {
  name        = "kookaburra-probe.storage.pod.haus"
  record_type = "A"
  value       = data.terraform_remote_state.relay.outputs.reserved_ip
  ttl         = 300
  enabled     = true
}
