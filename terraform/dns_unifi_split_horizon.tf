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

# voice.pod.haus → bilby directly on LAN, so the Mumble client skips
# the UDM hairpin (and the latency that adds, on a service where
# latency is exactly what we're optimising for). Off-LAN family hits
# the public A record → WAN-forward path (terraform/unifi.tf).
resource "unifi_dns_record" "voice_pod_haus" {
  name        = "voice.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = 300
  enabled     = true
}

# music.pod.haus → bilby (Caddy) on LAN. Home Assistant runs on bilby and
# its server-to-server websocket to Music Assistant can't carry a
# Cloudflare Access cookie, so it must reach MA without traversing the
# CF edge. This split-horizon record points LAN clients (and bilby's own
# host resolver, which HA shares via network_mode: host) at Caddy, which
# fronts MA with a real LE cert. Off-LAN browsers use the public CF
# record → tunnel. See caddy/Caddyfile + MA base_url = https://music.pod.haus.
resource "unifi_dns_record" "music_pod_haus" {
  name        = "music.pod.haus"
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
# Source of truth: the digitalocean_reserved_ip.kookaburra resource
# (intra-root reference; was terraform_remote_state pre-consolidation).
resource "unifi_dns_record" "kookaburra_probe_storage" {
  name        = "kookaburra-probe.storage.pod.haus"
  record_type = "A"
  value       = digitalocean_reserved_ip.kookaburra.ip_address
  ttl         = 300
  enabled     = true
}
