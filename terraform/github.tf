# Podhaus push-to-deploy: CI, not a webhook, starts the deploy.
#
# A push to main runs .github/workflows/check.yml. Its deploy job, which
# runs only after every check passes, calls the `podhaus-push-deploy`
# Procedure's Komodo listener with the signed body a GitHub push webhook
# would send:
#
#   https://komodo.pod.haus/listener/github/procedure/podhaus-push-deploy/main
#
# Komodo checks only the X-Hub-Signature-256 HMAC over the body, against
# KOMODO_WEBHOOK_SECRET (the procedure's own webhook_secret is empty, so
# the global one applies), and the branch in the body's `ref`. The final
# path segment is that branch filter. The procedure fans out internally
# (komodo/sync/procedures.toml), so new stacks need no edit here.
#
# Pomerium allows only the path-scoped /listener/github prefix without
# browser auth.
#
# Reference docs:
#   - github_actions_secret (integrations/github v6):
#     https://registry.terraform.io/providers/integrations/github/latest/docs/resources/actions_secret
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

resource "github_actions_secret" "komodo_webhook_secret" {
  repository  = "podhaus"
  secret_name = "KOMODO_WEBHOOK_SECRET"
  value       = var.komodo_webhook_secret
}

# Fenwick and nathanbaxter live on Forgejo; their push webhooks are
# forgejo_repository_webhook.komodo_deploy in forgejo.tf.

# Sibling webhook for the pets engine repo. Same global secret +
# Pomerium machine exception for /listener/github. Fires
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

# nb-macbook-pro's machine key, read from the same file that feeds the
# Forgejo ssh_keys claim in pocket_id.tf. Requires the admin:public_key
# scope on the Homelab GitHub PAT.
#
# The `moved` block below carries the registration over from the retired
# nb-macbook-air's resource address. The provider forces a new resource on
# any title change, so a title change deletes and recreates the key.
#
# Only the type and key-material fields are sent: GitHub stores keys with
# the comment stripped, and the provider's DiffSuppressFunc only trims
# whitespace — a comment-bearing value would diff forever and, with
# ForceNew on `key`, delete and recreate the key on every apply.
#
# This registers authentication only. The Verified badge needs the same key
# registered as an SSH *signing* key, and the provider has no resource for
# those (only /user/keys, not /user/ssh_signing_keys) — every fleet machine
# key is added there out-of-band (github.com/settings/keys or the API with
# the admin:ssh_signing_key scope).
#
# Reference doc (integrations/github v6):
#   https://registry.terraform.io/providers/integrations/github/latest/docs/resources/user_ssh_key
moved {
  from = github_user_ssh_key.nb_macbook_air_machine
  to   = github_user_ssh_key.nb_macbook_pro_machine
}

resource "github_user_ssh_key" "nb_macbook_pro_machine" {
  title = "nb-macbook-pro machine key"
  key = join(" ", slice(
    split(" ", trimspace(file("${path.module}/../forgejo/keys/nathan/nb-macbook-pro-machine.pub"))),
    0, 2,
  ))
}

# bandicoot's machine key, on the same terms as nb-macbook-pro's above:
# authentication only, from the file that feeds the Forgejo claim; the
# signing-key registration stays out-of-band.
resource "github_user_ssh_key" "bandicoot_machine" {
  title = "bandicoot machine key"
  key = join(" ", slice(
    split(" ", trimspace(file("${path.module}/../forgejo/keys/nathan/bandicoot-machine.pub"))),
    0, 2,
  ))
}

# Sibling webhook for the docs-server repo (the central docs.pod.haus
# service). Same global secret + Pomerium machine exception (path-scoped
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

resource "github_user_ssh_key" "quokka_machine" {
  title = "quokka machine key"
  key = join(" ", slice(
    split(" ", trimspace(file("${path.module}/../forgejo/keys/nathan/quokka-machine.pub"))),
    0, 2,
  ))
}
