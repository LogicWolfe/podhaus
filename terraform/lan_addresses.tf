# The fleet's home-LAN addresses — one definition per device, and the
# handoff that lets everything else read it.
#
# The locals below are the ONLY place a 10.0.0.0/24 address is written down
# in this repository. Three things flow from them and nothing re-states them:
#
#   - unifi.tf's `unifi_client` reservations, which make each address true
#     by pinning the DHCP lease to the device's MAC;
#   - dns_unifi_split_horizon.tf's LAN records, which give each address a
#     name;
#   - onepassword_item.podhaus_lan_addresses below, which carries the values
#     to every consumer outside Terraform.
#
# The 1Password handoff is the same contract Numbat's public addresses
# already use (binarylane.tf publishes them beside the break-glass
# credential; ansible/inventory/host_vars/numbat.yml reads them back). Here
# it feeds two readers: Ansible, through the `community.general.onepassword`
# lookups in ansible/inventory/group_vars/all.yml, and Komodo, through
# komodo-op — which turns each field into an
# `OP__KOMODO__PODHAUS_LAN_ADDRESSES__<FIELD>` Variable that stack.toml
# environment blocks reference and compose files consume as `${…}`.
#
# Deliberately not DNS-derived: the split-horizon records are consumers of
# these same values, so resolving them would be circular and would lag
# exactly when an address changes.
locals {
  # bilby, on end0. Every LAN-published port on the primary host is reached
  # here: Gatus's heartbeat listener, Bugsink's ingest, Mumble's WAN
  # forward, and the git.pod.haus origin the Forgejo runner and Komodo Core
  # pin past Pomerium.
  bilby_ip = "10.0.0.119"
  # bandicoot's USB Ethernet adapter (Asahi has no Thunderbolt, so the 1 GbE
  # link is a Realtek RTL8153 on USB). Komodo Core, the ClickStack OTLP
  # collector, MeTube and Sonarr all answer here.
  bandicoot_ip = "10.0.0.90"
  # kangaroo (the QNAP). Both NICs are cabled and both reserved; consumers
  # follow the 10GbE link, which is the active path.
  kangaroo_ip_1g  = "10.0.0.232"
  kangaroo_ip_10g = "10.0.0.25"
  # The Windows desktop hosting the fractal WSL guest; forwards only :22
  # into it. Reserved so the split-horizon fractal.pod.haus record and
  # every ssh config pointing at it stay truthful.
  fractal_windows_ip = "10.0.0.70"
  # The ESP32 bridging the burrow Turn Touch. Reserved because Alloy scrapes
  # its /metrics by IP — Docker's resolver has no mDNS, so the .local name is
  # unreachable from the container and a DHCP drift would end the scrape
  # silently.
  turn_touch_burrow_ip = "10.0.0.238"
  # The ESP32 switching the grasshopper LED strip. Reserved for the same
  # reason as the Turn Touch: Alloy scrapes its /metrics by IP.
  led_strip_grasshopper_ip = "10.0.0.44"
  # The Pi Zero bridging the Flic buttons. Nothing dials it any more — the
  # Pi pushes to a Home Assistant webhook — but it is a managed host reached
  # by address for SSH and the scan wizard, so the lease stays pinned.
  pizero_ip = "10.0.0.77"
  # Nathan's MacBook Air (wifi). Reserved so the split-horizon
  # nb-macbook-air.pod.haus record and its Ansible connection stay truthful.
  nb_macbook_air_ip = "10.0.0.202"
}

# The published subset: exactly the addresses something outside Terraform
# reads. A device whose address is used only by Terraform (the spare
# kangaroo NIC, the Windows desktop, the Pi Zero, the MacBook Air) is
# reserved above and reached by its split-horizon name, so it has nothing
# to publish. Adding a field here is what makes a new address available to
# Ansible and to Komodo stacks; komodo-op picks it up within a minute.
#
# These are not secrets. They live in the Homelab vault because that vault
# is the fleet's one distribution channel — the same reason Numbat's public
# addresses ride "Numbat Root".
resource "onepassword_item" "podhaus_lan_addresses" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Podhaus LAN Addresses"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    LAN = {
      field_map = {
        bilby_ipv4 = {
          type  = "STRING"
          value = local.bilby_ip
        }
        bandicoot_ipv4 = {
          type  = "STRING"
          value = local.bandicoot_ip
        }
        kangaroo_ipv4 = {
          type  = "STRING"
          value = local.kangaroo_ip_10g
        }
        turn_touch_burrow_ipv4 = {
          type  = "STRING"
          value = local.turn_touch_burrow_ip
        }
        led_strip_grasshopper_ipv4 = {
          type  = "STRING"
          value = local.led_strip_grasshopper_ip
        }
      }
    }
  }
}
