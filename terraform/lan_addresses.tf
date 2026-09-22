# The catalog also feeds Ansible, bootstrap commands and generated Komodo
# variables, so a reservation and every consumer use the same address.
locals {
  lan_addresses            = jsondecode(file("${path.module}/../config/lan-addresses.json"))
  bilby_ip                 = local.lan_addresses.bilby_ipv4
  bandicoot_ip             = local.lan_addresses.bandicoot_ipv4
  kangaroo_ip_1g           = local.lan_addresses.kangaroo_1g_ipv4
  kangaroo_ip_10g          = local.lan_addresses.kangaroo_ipv4
  fractal_windows_ip       = local.lan_addresses.fractal_windows_ipv4
  turn_touch_burrow_ip     = local.lan_addresses.turn_touch_burrow_ipv4
  led_strip_grasshopper_ip = local.lan_addresses.led_strip_grasshopper_ipv4
  pizero_ip                = local.lan_addresses.pizero_ipv4
  nb_macbook_air_ip        = local.lan_addresses.nb_macbook_air_ipv4
}
