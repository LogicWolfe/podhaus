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
  image      = "fedora-43-x64"
  name       = "kookaburra"
  region     = "syd1"
  size       = "s-1vcpu-512mb-10gb"
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
  # SSH locked to bilby's home WAN + the Tailscale CGNAT range.
  # Originally open to the world for the Periphery bootstrap; the
  # public exposure attracted enough internet SSH-scanner pressure to
  # keep sshd's MaxStartups (10:30:100) unauthenticated-session
  # counter in the random-early-drop band, RST-ing legit connections
  # from bilby (kex_exchange_identification: read: Connection reset
  # by peer). Locking the source set eliminates the noise — and SSH
  # is no longer reachable from anywhere else on the internet.
  #
  # bilby.wan:    144.6.147.203/32 (home; static-ish — if it ever
  #               changes, recovery is via the tailnet route).
  # tailscale:    100.64.0.0/10 (Tailscale CGNAT range — any
  #               tag:podnet node, incl. bilby's tailscale stack).
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["144.6.147.203/32", "100.64.0.0/10"]
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
