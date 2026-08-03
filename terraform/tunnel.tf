# Voltaire's connector lives on Voltaire. Terraform owns only the Cloudflare
# tunnel resource; no Voltaire service configuration belongs in podhaus.
resource "cloudflare_zero_trust_tunnel_cloudflared" "voltaire" {
  account_id = var.account_id
  name       = "voltaire"
  config_src = "local"
}
