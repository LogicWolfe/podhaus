# Single GitHub push webhook for Komodo push-to-deploy.
#
# Komodo's webhook contract is per-resource:
#
#   https://<HOST>/listener/<auth>/<resource_type>/<id_or_name>/<seg>
#
# We do NOT register one webhook per Stack: GitHub hard-caps a repo at
# 20 `push` webhooks ("the push event cannot have more than 20 hooks")
# and the fleet is past 20. Instead ONE webhook targets the
# `podhaus-push-deploy` Procedure's listener (resource_type
# `procedure`; the final path segment is the branch filter, not an
# execution verb — see Komodo 1.19.5 bin/core/src/listener/router.rs
# "/procedure/{id}/{branch}"). The procedure fans out internally:
#   - Stage 1 BatchDeployStackIfChanged "*"  — every stack, deploy
#     only if its files changed (bilby no-churn; kangaroo no-ops here)
#   - Stage 2 BatchDeployStack "kangaroo-*"  — force-deploy the
#     linked_repo stacks (replaces per-stack webhook_force_deploy)
# Defined config-as-code in komodo/sync/procedures.toml. New stacks
# are covered automatically by the "*" pattern — no edit here, ever.
#
# GitHub fires on every push to `main`; the `/main` branch segment
# makes Komodo act only on main pushes. `webhook_enabled` defaults
# true on the procedure (pinned true in procedures.toml).
#
# Delivery path is bypassed in Access by the path-scoped app
# (cloudflare_zero_trust_access_application.komodo_webhook in
# access.tf), scoped to the /listener/github prefix. Komodo validates
# the X-Hub-Signature-256 HMAC against KOMODO_WEBHOOK_SECRET itself
# (the procedure's webhook_secret is empty → global secret is used).
#
# Reference docs:
#   - github_repository_webhook (integrations/github v6):
#     https://registry.terraform.io/providers/integrations/github/latest/docs/resources/repository_webhook
#
# Rotation: change the secret in
# op://Homelab/Komodo Webhook Secret/password, restart Komodo Core so
# it picks up the new env (komodo/compose.env reads it via op://), and
# `tf apply` to push the matching secret to GitHub.

variable "komodo_webhook_secret" {
  description = "HMAC secret shared between GitHub and Komodo. Set via TF_VAR_komodo_webhook_secret env (resolved at chezmoi-render time from op://Homelab/Komodo Webhook Secret/password)."
  type        = string
  sensitive   = true
}

resource "github_repository_webhook" "komodo_deploy" {
  repository = "podhaus"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/listener/github/procedure/podhaus-push-deploy/main"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}
