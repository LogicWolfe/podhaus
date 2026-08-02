output "reserved_ip" {
  description = "Stable public IP for kookaburra — the storage.pod.haus A-record target (set in the cloudflare/ root at DNS cutover)."
  value       = digitalocean_reserved_ip.kookaburra.ip_address
}

output "droplet_ipv4" {
  description = "kookaburra's own droplet IPv4 (for the SSH Periphery bootstrap)."
  value       = digitalocean_droplet.kookaburra.ipv4_address
}

output "numbat_application_ipv4" {
  description = "Numbat address for Pomerium HTTPS and Forgejo SSH."
  value       = local.numbat_application_ipv4
}

output "numbat_relay_ipv4" {
  description = "Numbat address for rathole TLS/control and Pomerium SSH."
  value       = local.numbat_relay_ipv4
}

output "numbat_ssh_host_public_key" {
  description = "Pinned ED25519 host key used by numbat_bootstrap."
  value       = tls_private_key.numbat_ssh_host.public_key_openssh
}
