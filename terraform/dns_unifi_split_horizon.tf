# UniFi-side LAN DNS: split-horizon overrides for pod.haus hostnames
# that resolve to internal IPs when the requester is on the home
# network. The public A records (managed in services_pod_haus.tf and pointing
# to Numbat) take precedence over these for off-LAN requests;
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
  # Keep Terraform's public API URL on a valid Caddy certificate on-LAN too.
  value   = "10.0.0.119"
  ttl     = "5m0s"
  enabled = true
}

resource "unifi_dns_record" "bilby_pod_haus" {
  name        = "bilby.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = "5m0s"
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
  ttl         = "5m0s"
  enabled     = true
}

# Pouch MinIO follows the same split path as the primary storage endpoint.
# LAN clients reach bilby's Caddy directly; remote clients use Numbat.
resource "unifi_dns_record" "pouch_pod_haus" {
  name        = "pouch.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = "5m0s"
  enabled     = true
}

# Publii uploads to <bucket>.storage.pod.haus (virtual-host). Keep LAN
# publishes off the WAN/hairpin path (was the cause of VPN-MTU TLS
# handshake failures from a home laptop). One per Publii site.
resource "unifi_dns_record" "nathanbaxter_com_storage" {
  name        = "nathanbaxter-com.storage.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = "5m0s"
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
  ttl         = "5m0s"
  enabled     = true
}

# fractal.pod.haus → the Windows host's :22 forward, LAN only. The name
# is SSH-only — fractal has no HTTPS route at this name (fractal.docs.
# pod.haus is a separate name and stays on Pomerium), so unlike kangaroo
# there is no HTTPS identity boundary for a split record to leak. There
# is deliberately NO public record: off-LAN SSH rides the ssh.pod.haus
# Pomerium route via the chezmoi ssh config rewrite. LAN clients (and
# bilby-resident agents) connect direct, keeping fractal reachable even
# when the Pomerium edge is not.
resource "unifi_dns_record" "fractal_pod_haus" {
  name        = "fractal.pod.haus"
  record_type = "A"
  value       = local.fractal_windows_ip
  ttl         = "5m0s"
  enabled     = true
}

# nb-macbook-air.pod.haus → the MacBook Air's reserved wifi address, LAN
# only. SSH-only, like fractal: there is no HTTPS route and deliberately no
# public or Pomerium record — the Mac has no inbound path from outside the
# home network. LAN clients (bilby-resident agents running its Ansible
# playbook, and Nathan moving between machines) connect direct.
resource "unifi_dns_record" "nb_macbook_air_pod_haus" {
  name        = "nb-macbook-air.pod.haus"
  record_type = "A"
  value       = local.nb_macbook_air_ip
  ttl         = "5m0s"
  enabled     = true
}

# music.pod.haus → bilby (Caddy) on LAN. Home Assistant runs on bilby and
# its server-to-server websocket to Music Assistant can't carry a
# browser session, so it must reach MA without traversing the
# CF edge. This split-horizon record points LAN clients (and bilby's own
# host resolver, which HA shares via network_mode: host) at Caddy, which
# fronts MA with a real LE cert. Off-LAN browsers use the public CF
# record → tunnel. See caddy/Caddyfile + MA base_url = https://music.pod.haus.
resource "unifi_dns_record" "music_pod_haus" {
  name        = "music.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = "5m0s"
  enabled     = true
}
