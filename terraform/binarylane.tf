locals {
  numbat_application_ipv4 = "103.1.184.88"
  numbat_relay_ipv4       = "103.4.235.175"
}

resource "binarylane_ssh_key" "numbat" {
  name       = "numbat"
  public_key = file("${path.module}/ssh_authorized_key.pub")
}

resource "onepassword_item" "numbat_root" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Numbat Root"
  category = "login"
  url      = "https://home.binarylane.com.au/servers/644361"
  username = "root"
  tags     = ["terraform-managed", "break-glass"]

  password_recipe {
    length  = 63
    digits  = true
    symbols = false
  }
}

# Numbat is the Perth gateway replacing Kookaburra after cutover.
resource "binarylane_server" "numbat" {
  name              = "numbat.pod.haus"
  region            = "per"
  image             = "rocky-10"
  size              = "std-min"
  public_ipv4_count = 2
  backups           = false
  ipv6              = false
  password          = onepassword_item.numbat_root.password
  port_blocking     = true
  ssh_keys          = [binarylane_ssh_key.numbat.id]
  user_data = templatefile("${path.module}/numbat/cloud-init.yaml.tftpl", {
    application_ipv4       = local.numbat_application_ipv4
    relay_ipv4             = local.numbat_relay_ipv4
    relay_ip_dispatcher    = indent(6, file("${path.module}/../numbat/host/20-relay-ip"))
    bootstrap_sshd_config  = indent(6, file("${path.module}/../numbat/host/bootstrap-sshd_config"))
    bootstrap_sshd_service = indent(6, file("${path.module}/../numbat/host/bootstrap-sshd.service"))
    nathan_authorized_key  = trimspace(file("${path.module}/ssh_authorized_key.pub"))
    pomerium_ssh_user_ca   = trimspace(tls_private_key.pomerium_ssh_user_ca.public_key_openssh)
  })

  # cloud-init is first-boot input. Host reconciliation after creation is
  # numbat_bootstrap; changing this template must not replace the gateway.
  lifecycle {
    ignore_changes = [user_data]
  }
}
