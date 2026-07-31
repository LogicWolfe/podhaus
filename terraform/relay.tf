# kookaburra — the public ingress relay droplet. Runs the rathole
# SERVER (public :443 data + :2333 control, noise+token); bilby dials
# out. TLS still terminates at bilby's Caddy — the droplet only ever
# sees ciphertext. See docs/plans/storage-public-relay.md.

data "digitalocean_project" "podhaus" {
  name = "podhaus"
}

resource "digitalocean_ssh_key" "kookaburra" {
  name       = "kookaburra"
  public_key = file("${path.module}/ssh_authorized_key.pub")
}

resource "digitalocean_droplet" "kookaburra" {
  image  = "fedora-43-x64"
  name   = "kookaburra"
  region = "syd1"
  # 1GB (not 512MB) — three concurrent Komodo DeployStack ops on
  # 512MB OOM-thrashed the box (load avg 27, sshd wedged). With four
  # Komodo-managed stacks now riding here (tailscale, periphery is
  # bootstrap-managed but still on it, relay, logging) plus headroom
  # for restic/apt during cattle rebuilds, 1GB is the realistic floor.
  size       = "s-1vcpu-1gb"
  ssh_keys   = [digitalocean_ssh_key.kookaburra.fingerprint]
  monitoring = true
  ipv6       = false
  tags       = ["podhaus", "relay"]

  # Minimal cloud-init: just get Docker so the SSH bootstrap
  # (kookaburra_bootstrap, paralleling kangaroo_bootstrap) can bring
  # up Periphery + the rathole/tailscale stacks. Docker's convenience
  # script supports Fedora and includes the compose plugin.
  user_data = <<-EOT
    #cloud-config
    package_update: true
    runcmd:
      - [ sh, -c, "curl -fsSL https://get.docker.com | sh" ]
      - [ systemctl, enable, --now, docker ]
  EOT

  lifecycle {
    # The relay is stateless/disposable; user_data change shouldn't
    # silently destroy a working relay — rebuilds are deliberate.
    ignore_changes = [user_data]
  }
}

resource "digitalocean_reserved_ip" "kookaburra" {
  region = "syd1"
}

resource "digitalocean_reserved_ip_assignment" "kookaburra" {
  ip_address = digitalocean_reserved_ip.kookaburra.ip_address
  droplet_id = digitalocean_droplet.kookaburra.id
}

resource "digitalocean_firewall" "kookaburra" {
  name        = "kookaburra-relay"
  droplet_ids = [digitalocean_droplet.kookaburra.id]

  # Public data + rathole control. Control is public BY DESIGN —
  # secured by rathole's mandatory token + noise transport, not IP
  # pinning (which would be fragile against bilby's dynamic WAN IP).
  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }
  inbound_rule {
    protocol         = "tcp"
    port_range       = "2333"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }
  # Port 22 has two address-specific owners on the droplet. Host sshd
  # binds the ordinary public IPv4 for cattle-rebuild recovery. Rathole
  # binds DigitalOcean's anchor IPv4; traffic sent to the Reserved IP
  # (git.pod.haus) maps there and is relayed to Forgejo on bilby.
  # kookaburra/ssh-hardening/apply.sh owns the bind + nftables split.
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # A DO firewall with NO outbound block silently drops ALL egress
  # (breaks Tailscale, dnf, the rathole dial). Allow all egress —
  # this box's control objective is inbound.
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

resource "digitalocean_project_resources" "kookaburra" {
  project = data.digitalocean_project.podhaus.id
  resources = [
    digitalocean_droplet.kookaburra.urn,
    digitalocean_reserved_ip.kookaburra.urn,
  ]
}
