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

# storage.pod.haus → bilby directly for LAN clients, so Terraform run
# from bilby/LAN (path-style) hits Caddy without NAT hairpin off the
# public A record. Off-LAN clients (Sky's Publii) use the grey-cloud
# Cloudflare record → WAN port-forward. (Wildcard vhost names from LAN
# fall through to the public path/hairpin — fine; Publii is off-LAN.)
resource "unifi_dns_record" "storage_pod_haus" {
  name        = "storage.pod.haus"
  record_type = "A"
  value       = "10.0.0.119"
  ttl         = 300
  enabled     = true
}
