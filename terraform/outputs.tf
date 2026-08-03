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
