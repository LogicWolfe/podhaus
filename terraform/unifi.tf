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

# DHCP reservation pinning kangaroo (the QNAP) to a stable LAN IP, so a
# reboot can't drift it off the address every consumer expects. Bound to
# eth0's MAC — the 1GbE NIC the box reliably gets a lease on (the 10GbE
# eth1 lost its IP config in the 2026-06 power event). Replaces the old
# manually-maintained reservation; the IP is `local.kangaroo_lan_ip`, the
# single source of truth also feeding the Cloudflare-tunnel backends.
# Import (existing client): terraform import unifi_client.kangaroo 6a1d392d4f9fa3fc2042ea93
resource "unifi_client" "kangaroo" {
  mac      = "24:5e:be:29:78:bf"
  name     = "Kangaroo"
  fixed_ip = local.kangaroo_lan_ip
  # No network_id: the client is on the Default LAN, and setting it triggers a
  # virtual-network override UniFi rejects for the default network.
}
