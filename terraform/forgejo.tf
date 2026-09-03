# Forgejo (git.pod.haus) — repository policy and deploy-pipeline wiring.
#
# Provider choice: kfkonrad/forgejo (Forgejo-native, actively released
# fork of svalabs/forgejo) over go-gitea/gitea. It tracks Forgejo's own
# API — Forgejo 16 has diverged from Gitea — and covers everything
# needed here: repository data source, deploy keys, and a webhook
# resource whose secret is a write-only top-level attribute (the
# svalabs parent stores it in the config map and fails apply because
# Forgejo never echoes it back; svalabs#158). See backend.tf.
#
# The repository itself is deliberately a DATA SOURCE, not a resource:
# the migrated repo is the source of truth for nathanbaxter.com, and a
# Terraform-owned repo resource could destroy or replace it on drift.
# The one-time migration was done via POST /api/v1/repos/migrate.
#
# The provider reaches Forgejo through the public https://git.pod.haus
# name (never dockernet/loopback — the from-any-machine TF contract).
# Pomerium passes /api/v1 unauthenticated (pomerium/config.yaml);
# Forgejo's own token auth is the boundary, same stance as MinIO SigV4.

data "onepassword_item" "forgejo_terraform" {
  vault = data.onepassword_vault.homelab.uuid
  title = "Forgejo Terraform"
}

provider "forgejo" {
  host      = "https://git.pod.haus"
  api_token = data.onepassword_item.forgejo_terraform.credential
}

data "forgejo_repository" "nathanbaxter" {
  owner = "LogicWolfe"
  name  = "nathanbaxter"
}

data "forgejo_repository" "yiayia_stories" {
  owner = "LogicWolfe"
  name  = "yiayia-stories"
}

# Push webhook → Komodo's yiayia-stories-push-deploy procedure (linked-repo
# stack defined in that repository; see komodo/sync/procedures.toml).
resource "forgejo_repository_webhook" "yiayia_stories_deploy" {
  repository    = data.forgejo_repository.yiayia_stories.full_name
  type          = "forgejo"
  url           = "https://komodo.pod.haus/listener/github/procedure/yiayia-stories-push-deploy/main"
  content_type  = "json"
  secret        = var.komodo_webhook_secret
  branch_filter = "main"
  active        = true

  events {
    push = true
  }
}

# Fenwick was migrated through Forgejo's repository migration API, then
# imported into this resource. Terraform owns repository policy but must never
# be able to destroy source history.
resource "forgejo_repository" "fenwick" {
  owner       = "LogicWolfe"
  name        = "fenwick"
  description = "Fenwick — stateful Signal/email home-helper bot"
  private     = true

  default_branch    = "main"
  has_actions       = true
  has_issues        = true
  has_packages      = false
  has_projects      = false
  has_pull_requests = true
  has_releases      = true
  has_wiki          = false

  allow_merge_commits   = false
  allow_rebase          = false
  allow_rebase_explicit = false
  allow_squash_merge    = true
  default_merge_style   = "squash"
  archive_on_destroy    = true

  lifecycle {
    prevent_destroy = true
  }
}

# Main is review + CI territory. These are the exact contexts emitted by the
# proven pull-request workflow; the post-merge main workflow independently
# gates deployment before it may advance `deploy`.
resource "forgejo_repository_branch_rule" "fenwick_main" {
  repository               = forgejo_repository.fenwick.full_name
  protected_branch_pattern = "main"
  enable_push              = true
  enable_push_whitelist    = true
  push_whitelist_usernames = ["LogicWolfe"]
  enable_status_check      = true
  status_check_contexts = [
    "CI / deno (pull_request)",
    "CI / webui (pull_request)",
    "CI / web-agent (pull_request)",
  ]
  block_on_outdated_branch = true
  dismiss_stale_approvals  = true
}

# `deploy` is the auditable promotion pointer. The green main workflow moves it
# forward without force; this webhook is the sole automatic deploy trigger.
resource "forgejo_repository_webhook" "fenwick_deploy" {
  repository    = forgejo_repository.fenwick.full_name
  type          = "forgejo"
  url           = "https://komodo.pod.haus/listener/github/procedure/fenwick-push-deploy/deploy"
  content_type  = "json"
  secret        = var.komodo_webhook_secret
  branch_filter = "deploy"
  active        = true

  events {
    push = true
  }
}

# Read-only deploy key for the nathanbaxter-deploy builder container.
# The builder clones over dockernet SSH (git@forgejo:2222); HTTP git is
# disabled instance-wide.
resource "tls_private_key" "nathanbaxter_deploy" {
  algorithm = "ED25519"
}

resource "forgejo_deploy_key" "nathanbaxter_deploy" {
  repository_id = data.forgejo_repository.nathanbaxter.id
  key           = trimspace(tls_private_key.nathanbaxter_deploy.public_key_openssh)
  title         = "nathanbaxter-deploy"
  read_only     = true
}

# Push webhook → Komodo's nathanbaxter-deploy procedure. Replaces the
# github_repository_webhook that lived in github.tf. Forgejo sends
# GitHub-compatible X-GitHub-Event / X-Hub-Signature-256 headers, so
# Komodo's /listener/github endpoint validates it exactly like the
# GitHub original. The public komodo.pod.haus path rides the existing
# Pomerium /listener/github exception and avoids Forgejo's
# private-address webhook blocking. /main is Komodo's branch filter;
# branch_filter trims deliveries at the source too.
resource "forgejo_repository_webhook" "nathanbaxter_deploy" {
  repository    = data.forgejo_repository.nathanbaxter.full_name
  type          = "forgejo"
  url           = "https://komodo.pod.haus/listener/github/procedure/nathanbaxter-deploy/main"
  content_type  = "json"
  secret        = var.komodo_webhook_secret
  branch_filter = "main"
  active        = true

  events {
    push = true
  }
}

# Private half of the deploy key, published for komodo-op → Komodo
# Variable OP__KOMODO__NATHANBAXTER_DEPLOY_KEY__PRIVATE_KEY_B64,
# consumed by nathanbaxter-deploy/stack.toml.
resource "onepassword_item" "nathanbaxter_deploy_key" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Nathanbaxter Deploy Key"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    Key = {
      field_map = {
        private_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.nathanbaxter_deploy.private_key_openssh)
        }
      }
    }
  }
}
