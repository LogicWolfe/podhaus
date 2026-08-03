locals {
  numbat_application_ipv4 = binarylane_server.numbat.public_ipv4_addresses[0]
  numbat_relay_ipv4       = binarylane_server.numbat.public_ipv4_addresses[1]
}

resource "binarylane_ssh_key" "numbat" {
  name       = "numbat"
  public_key = file("${path.module}/ssh_authorized_key.pub")
}

resource "binarylane_ssh_key" "numbat_piv" {
  name       = "numbat-piv"
  public_key = file("${path.module}/operator_piv_authorized_key.pub")
}

# Stable across VPS replacement so numbat_bootstrap can verify the new host
# before sending any credentials. The private half exists only in Terraform
# state and the replacement's first-boot metadata.
resource "tls_private_key" "numbat_ssh_host" {
  algorithm = "ED25519"
}

resource "random_password" "numbat_bootstrap" {
  length  = 63
  special = false
}

resource "random_password" "numbat_root" {
  length  = 63
  special = false
}

resource "onepassword_item" "numbat_root" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Numbat Root"
  category = "login"
  url      = "https://home.binarylane.com.au/servers"
  username = "root"
  password = random_password.numbat_root.result
  tags     = ["terraform-managed", "break-glass"]

  # Host facts the numbat Ansible plays consume, published beside the
  # break-glass credential so they ride the one distribution channel
  # instead of a `terraform output` shell-out on the control node.
  # Deliberately not DNS-derived: a lookup would reconstruct these from
  # records that are themselves consumers of the same locals.
  section_map = {
    Host = {
      field_map = {
        application_ipv4 = {
          type  = "STRING"
          value = local.numbat_application_ipv4
        }
        relay_ipv4 = {
          type  = "STRING"
          value = local.numbat_relay_ipv4
        }
        ssh_host_key_pub = {
          type  = "STRING"
          value = trimspace(tls_private_key.numbat_ssh_host.public_key_openssh)
        }
      }
    }
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
  # BinaryLane emails this creation-only password in plaintext. Bootstrap
  # replaces it with the distinct 1Password-held root credential.
  password      = random_password.numbat_bootstrap.result
  port_blocking = true
  ssh_keys      = [binarylane_ssh_key.numbat.id, binarylane_ssh_key.numbat_piv.id]
  user_data = templatefile("${path.module}/numbat/cloud-init.yaml.tftpl", {
    bootstrap_sshd_config  = indent(6, file("${path.module}/../numbat/host/bootstrap-sshd_config"))
    bootstrap_sshd_service = indent(6, file("${path.module}/../numbat/host/bootstrap-sshd.service"))
    nathan_authorized_key  = trimspace(file("${path.module}/ssh_authorized_key.pub"))
    pomerium_ssh_user_ca   = trimspace(tls_private_key.pomerium_ssh_user_ca.public_key_openssh)
    ssh_host_private_key   = indent(6, trimspace(tls_private_key.numbat_ssh_host.private_key_openssh))
    ssh_host_public_key    = trimspace(tls_private_key.numbat_ssh_host.public_key_openssh)
  })

  # cloud-init is first-boot input. Host reconciliation after creation is
  # numbat_bootstrap; changing this template must not replace the gateway.
  lifecycle {
    create_before_destroy = true
    ignore_changes        = [user_data]
  }
}
