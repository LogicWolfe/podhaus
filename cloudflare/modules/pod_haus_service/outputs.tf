output "fqdn" {
  description = "Fully qualified hostname this module exposes."
  value       = local.fqdn
}

output "dns_record_id" {
  value = cloudflare_dns_record.this.id
}

output "access_app_id" {
  value = cloudflare_zero_trust_access_application.this.id
}

output "access_app_aud" {
  description = "Audience tag — useful for downstream stacks that need to validate the CF Access JWT directly."
  value       = cloudflare_zero_trust_access_application.this.aud
}

output "ingress_rule" {
  description = "Structured tunnel ingress entry. Concatenate from every module instance into cloudflare_zero_trust_tunnel_cloudflared_config.config.ingress."
  value       = local.ingress_rule
}
