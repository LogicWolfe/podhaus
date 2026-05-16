# GitHub webhooks for Komodo push-to-deploy.
#
# Komodo has NO single generic webhook endpoint. Its only contract is
# per-resource:
#
#   https://<HOST>/listener/<auth>/<resource_type>/<id_or_name>/<execution>
#
# So one webhook per Komodo Stack, each hitting that stack's `/deploy`
# listener. GitHub fires every webhook on every push to `main`; Komodo
# only acts when the pushed branch matches the resource's branch
# (default `main`), and a Stack `/deploy` `git pull`s its source before
# composing — so unchanged stacks are a `docker compose up -d` no-op,
# and linked-repo stacks (kangaroo) refresh their clone automatically.
# `webhook_enabled` defaults to true on every Komodo resource, so no
# stack.toml change is needed.
#
# Delivery path is bypassed in Access by the path-scoped app
# (cloudflare_zero_trust_access_application.komodo_webhook in
# access.tf), scoped to the /listener/github prefix. Komodo validates
# the X-Hub-Signature-256 HMAC against KOMODO_WEBHOOK_SECRET itself.
#
# Reference docs:
#   - github_repository_webhook (integrations/github v6):
#     https://registry.terraform.io/providers/integrations/github/latest/docs/resources/repository_webhook
#   - Komodo webhook contract: https://komo.do/docs/automate/webhooks
#
# Rotation: change the secret in
# op://Homelab/Komodo Webhook Secret/password, restart Komodo Core so
# it picks up the new env (komodo/compose.env reads it via op://), and
# `tf apply` to push the matching secret to GitHub.

variable "komodo_webhook_secret" {
  description = "HMAC secret shared between GitHub and Komodo. Set via TF_VAR_komodo_webhook_secret env (resolved by op run from op://Homelab/Komodo Webhook Secret/password)."
  type        = string
  sensitive   = true
}

locals {
  # Every Komodo Stack resource name — must mirror the `name =` value
  # in each <stack>/stack.toml (and <stack>/<host>/stack.toml for
  # multi-host stacks). Adding a service = add its stack.toml name
  # here so its push-to-deploy webhook is created. See AGENTS.md
  # "When adding a new service".
  #
  # HARD CEILING: GitHub allows at most 20 `push` webhooks per repo
  # ("the push event cannot have more than 20 hooks"). This list is AT
  # the cap. A 21st stack (bugsink) cannot get its own webhook — it is
  # deployed via `./komodo-sync` / manual first-deploy instead. Growing
  # past 20 push-to-deploy stacks needs a consolidation redesign (one
  # Procedure/Sync webhook fanning out), not another entry here.
  komodo_stacks = [
    "autoheal",
    "backup",
    "clickstack",
    "cloudflare-tunnel",
    "docs-server",
    "fenwick",
    "flood",
    "gatus",
    "home-assistant",
    "kangaroo-autoheal",
    "kangaroo-backup",
    "kangaroo-logging",
    "logging",
    "minio",
    "ofelia",
    "onepassword",
    "paperless",
    "plex",
    "syncthing",
    "unpackerr",
  ]
}

resource "github_repository_webhook" "komodo_deploy" {
  for_each = toset(local.komodo_stacks)

  repository = "podhaus"
  events     = ["push"]
  active     = true

  configuration {
    url          = "https://komodo.pod.haus/listener/github/stack/${each.value}/deploy"
    content_type = "json"
    insecure_ssl = false
    secret       = var.komodo_webhook_secret
  }
}
