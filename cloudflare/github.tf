# GitHub webhook for Komodo auto-deploy.
#
# GitHub pushes → POST https://komodo.pod.haus/auth/github/webhook,
# which is reachable via the path-scoped Bypass Access app
# (cloudflare_zero_trust_access_application.komodo_webhook in
# access.tf). Komodo validates the X-Hub-Signature-256 HMAC against
# KOMODO_WEBHOOK_SECRET on its end.
#
# Reference docs:
#   - integrations/github provider:
#     https://registry.terraform.io/providers/integrations/github/latest/docs
#   - github_repository_webhook resource:
#     https://registry.terraform.io/providers/integrations/github/latest/docs/resources/repository_webhook
#
# Rotation: change the secret in
# op://Homelab/Komodo Webhook Secret/password, restart Komodo Core so
# it picks up the new env (komodo/compose.env reads it via op://), and
# `tf apply` to push the matching secret to GitHub. All three sides
# update in one pass.

variable "komodo_webhook_secret" {
  description = "HMAC secret shared between GitHub and Komodo. Set via TF_VAR_komodo_webhook_secret env (resolved by op run from op://Homelab/Komodo Webhook Secret/password)."
  type        = string
  sensitive   = true
}

resource "github_repository_webhook" "komodo_deploy" {
  repository = "podhaus"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/auth/github/webhook"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}
