# voice.pod.haus is the Mumble voice server. Direct WAN ingress: this A
# record points at the home WAN IP; UDM port-forwards in
# terraform/unifi.tf send tcp+udp 64738 to bilby; the mumble stack
# binds the published ports. Mumble is not HTTP, so it does not use
# Pomerium HTTP path used by browser services. UDP is required for voice
# quality and that path can't carry
# arbitrary UDP. See docs/runbooks/mumble.md.
#
# DNS-only (grey-cloud): Cloudflare's HTTP proxy doesn't apply to a
# non-HTTP service, and we want the client's Mumble TLS to terminate
# at Murmur directly (TLS is part of the Mumble protocol). `content`
# is ignored here because the cloudflare-ddns stack owns it — TF owns
# the record's existence and shape, DDNS owns its current value.
#
# Bootstrap quirk: on first `terraform apply` this resource creates
# with `content = "0.0.0.0"` (a meaningless placeholder); the
# cloudflare-ddns container's next tick (~5m) overwrites it with the
# real WAN IP, after which DDNS keeps it fresh. Subsequent
# `terraform plan` calls will not show drift because of the lifecycle
# ignore. If you ever want to take DDNS out of the path entirely,
# remove the ignore and set `content` to the real IP here.
resource "cloudflare_dns_record" "voice_a" {
  zone_id = local.zones["pod.haus"]
  name    = "voice.pod.haus"
  type    = "A"
  content = "0.0.0.0"
  proxied = false
  ttl     = 300
  settings = {
    flatten_cname = false
    ipv4_only     = false
    ipv6_only     = false
  }
  lifecycle {
    ignore_changes = [content, settings]
  }
}
