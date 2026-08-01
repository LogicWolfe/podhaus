# UDM Pro SE WAN port-forwards. Default fleet ingress is the
# Cloudflare Tunnel (no exposed ports), so these resources exist only
# for services that genuinely cannot ride the Tunnel.
#
# Today that's Mumble: non-HTTP, UDP-load-bearing for voice quality
# (Tunnel can't carry arbitrary UDP). 64738 isn't bound by the UDM's
# own services, so the WAN:443 shadow trap that killed the old
# storage.pod.haus forward (UDM web UI binds WAN:443 itself) does not
# apply here. See docs/runbooks/mumble.md.
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

# DHCP reservations pinning kangaroo (the QNAP). Both NICs are cabled and
# both reserved, so neither can drift off the address consumers expect:
#   - eth0 1GbE (…78:bf) → kangaroo_ip_1g  (.232), the spare path
#   - eth1 10GbE (…78:c0) → kangaroo_ip_10g (.25), the active path
# Consumers follow local.kangaroo_active_ip (currently the 10GbE link).
# Both stay live; QTS's arp_ignore/announce keep the two same-subnet IPs
# from flapping. Import (existing clients):
#   terraform import unifi_client.kangaroo     6a1d392d4f9fa3fc2042ea93
#   terraform import unifi_client.kangaroo_10g 645c8c7f91871e0fa7119fec
resource "unifi_client" "kangaroo" {
  mac      = "24:5e:be:29:78:bf"
  name     = "Kangaroo"
  fixed_ip = local.kangaroo_ip_1g
  # No network_id: the client is on the Default LAN, and setting it triggers a
  # virtual-network override UniFi rejects for the default network.
}

resource "unifi_client" "kangaroo_10g" {
  mac      = "24:5e:be:29:78:c0"
  name     = "Kangaroo"
  fixed_ip = local.kangaroo_ip_10g
  # No network_id, same as the 1G client: this reservation predated TF with
  # a redundant Default-LAN virtual-network override, which UniFi rejects
  # setting on the default network — so TF clears it (client stays on .25 /
  # Default LAN). It also carries a Local DNS record (kangaroo.pod → .25)
  # that the provider preserves through updates.
}
