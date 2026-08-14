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
  # setting on the default network. SSH selects this active address locally;
  # DNS stays on Pomerium so the HTTPS identity boundary remains consistent.
}

# The Windows desktop hosting the fractal WSL guest. Pinned because the
# split-horizon fractal.pod.haus record (dns_unifi_split_horizon.tf) and
# fractal's Ansible connection both name this address; a DHCP drift would
# strand every direct path at once. Imported 2026-08-08 by MAC — the
# v0.53 provider imports clients by MAC, not by the controller id the
# kangaroo notes above describe.
resource "unifi_client" "fractal_windows" {
  mac      = "60:cf:84:e7:4e:c4"
  name     = "Fractal"
  fixed_ip = local.fractal_windows_ip
  # No network_id: Default LAN, same constraint as the kangaroo clients.
}

# The ESP32-C3 bridging the burrow Turn Touch into Home Assistant. Pinned
# because bilby's Alloy scrapes its Prometheus endpoint by address
# (logging/bilby/alloy-conf/config.alloy) and Home Assistant's ESPHome entry
# holds an address too. This client already exists in the controller as a DHCP
# lease, so import before the first apply:
#   terraform import unifi_client.turn_touch_burrow 1c:db:d4:f0:72:a8
resource "unifi_client" "turn_touch_burrow" {
  mac      = "1c:db:d4:f0:72:a8"
  name     = "Turn Touch Burrow"
  fixed_ip = local.turn_touch_burrow_ip
  # No network_id: Default LAN, same constraint as the kangaroo clients.
}

# The Pi Zero W running flicd, bridging the Flic buttons into Home
# Assistant. Pinned because HA's flic integration holds a fixed host:port
# (home-assistant/config/packages/flic.yaml) and cannot resolve mDNS from
# its container, so a DHCP drift would take every button offline silently.
# This client already exists in the controller as a DHCP lease, so import
# before the first apply:
#   terraform import unifi_client.pizero b8:27:eb:68:65:04
resource "unifi_client" "pizero" {
  mac      = "b8:27:eb:68:65:04"
  name     = "Pi Zero"
  fixed_ip = local.pizero_ip
  # No network_id: Default LAN, same constraint as the kangaroo clients.
}

# The XIAO ESP32C3 switching the grasshopper LED strip. Pinned for the same
# reason as the Turn Touch: Alloy scrapes its Prometheus endpoint by address
# (logging/bilby/alloy-conf/config.alloy), and Home Assistant's ESPHome config
# entry holds an address rather than a name. This client already exists in the
# controller as a DHCP lease, so import before the first apply:
#   terraform import unifi_client.led_strip_grasshopper ac:27:6e:81:e2:d8
resource "unifi_client" "led_strip_grasshopper" {
  mac      = "ac:27:6e:81:e2:d8"
  name     = "Grasshopper LED Strip"
  fixed_ip = local.led_strip_grasshopper_ip
  # No network_id: Default LAN, same constraint as the kangaroo clients.
}
