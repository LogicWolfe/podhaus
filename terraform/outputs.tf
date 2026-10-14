output "numbat_application_ipv4" {
  description = "Numbat address for Pomerium HTTPS and Forgejo SSH."
  value       = local.numbat_application_ipv4
}

output "numbat_relay_ipv4" {
  description = "Numbat address for the public TLS tunnel, the tunnel server, and Pomerium SSH."
  value       = local.numbat_relay_ipv4
}

output "numbat_ssh_host_public_key" {
  description = "Pinned ED25519 host key; the numbat bootstrap play reads it from 1Password."
  value       = tls_private_key.numbat_ssh_host.public_key_openssh
}
