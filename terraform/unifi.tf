# UDM Pro SE WAN port-forwards. Default fleet ingress is the
# Cloudflare Tunnel (no exposed ports), so these resources exist only
# for services that genuinely cannot ride the Tunnel.
#
# Today that's Mumble — non-HTTP, UDP-load-bearing for voice quality
# (Tunnel can't carry arbitrary UDP). 64738 isn't bound by the UDM's
# own services, so the WAN:443 shadow trap that killed the old
# storage.pod.haus forward (UDM web UI binds WAN:443 itself) does not
# apply here. See docs/plans/mumble-voice-pod-haus.md.
#
# Two single-protocol resources rather than a hypothetical
# `protocol = "tcp_udp"`: the v0.41 provider's `protocol` field is a
# string and the safe values are `tcp` / `udp`. Splitting also makes
# either side independently disable-able if we ever want to force
# clients onto TCP (or kill TCP fallback).
#
# Provider docs:
#   https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs/resources/port_forward
resource "unifi_port_forward" "mumble_udp" {
  name     = "voice.pod.haus (Mumble UDP)"
  protocol = "udp"

  wan = {
    port = "64738"
  }

  forward = {
    ip   = "10.0.0.119"
    port = "64738"
  }
}

resource "unifi_port_forward" "mumble_tcp" {
  name     = "voice.pod.haus (Mumble TCP)"
  protocol = "tcp"

  wan = {
    port = "64738"
  }

  forward = {
    ip   = "10.0.0.119"
    port = "64738"
  }
}
