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
# execution verb; see Komodo's listener router
# "/procedure/{id}/{branch}"). The procedure fans out internally:
#   - Stage 0 RunSync reconciles TOML definitions
#   - Stage 1 injects content hashes and directly reconciles stale
#     config/build-context consumers whose compose text did not change
#   - Stage 2 BatchDeployStackIfChanged "*" owns compose-text changes
#     and brand-new stacks
#   - Stage 3 restarts Ofelia so it re-reads scheduling labels
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
# `terraform apply` to push the matching secret to GitHub.

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

# Sibling webhook for the fenwick repo. Same global secret, same
# Access bypass (the path-scoped /listener/github application covers
# both — see access.tf). Fires the fenwick-push-deploy procedure
# (komodo/sync/procedures.toml): RunSync(fenwick) then a force
# BatchDeployStack "fenwick*" — both fenwick stacks are linked_repo +
# run_build, so Komodo builds the images on bilby; the Docker layer
# cache makes an unchanged push a container-level no-op. The /main
# segment is the Komodo branch filter — feature branches are
# ignored.
resource "github_repository_webhook" "fenwick_deploy" {
  repository = "fenwick"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/listener/github/procedure/fenwick-push-deploy/main"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}

# Sibling webhook for the nathanbaxter repo. Replaces the repo's
# previous .github/workflows/deploy.yml. Same global webhook secret,
# same Access bypass (the path-scoped /listener/github application
# covers it). Fires the nathanbaxter-deploy procedure
# (komodo/sync/procedures.toml) → DeployStack nathanbaxter-deploy →
# the one-shot builder container clones, builds, and mcli mirrors
# dist/ to the nathanbaxter-com bucket.
resource "github_repository_webhook" "nathanbaxter_deploy" {
  repository = "nathanbaxter"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/listener/github/procedure/nathanbaxter-deploy/main"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}

# Sibling webhook for the pets engine repo. Same global secret +
# Access bypass (path-scoped /listener/github app in access.tf). Fires
# pets-push-deploy (komodo/sync/procedures.toml): RunSync then a
# force BatchDeployStack "pets*" — linked_repo + run_build, so
# Komodo builds the image on bilby; the layer cache makes an unchanged
# push a container-level no-op. /main is the branch filter.
resource "github_repository_webhook" "pets_deploy" {
  repository = "pets"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/listener/github/procedure/pets-push-deploy/main"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}

# Sibling webhook for the docs-server repo (the central docs.pod.haus
# service). Same global secret + Access bypass (path-scoped
# /listener/github app in access.tf). Fires docs-push-deploy
# (komodo/sync/procedures.toml): RunSync(docs) then a force
# BatchDeployStack "docs" — linked_repo + run_build, so Komodo builds
# the image on bilby; the layer cache makes an unchanged push a
# container-level no-op. /main is the branch filter.
resource "github_repository_webhook" "docs_deploy" {
  repository = "docs-server"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/listener/github/procedure/docs-push-deploy/main"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}
