# Forgejo (git.pod.haus) — deploy-pipeline wiring for repos that moved
# off GitHub. Currently just LogicWolfe/nathanbaxter, migrated 2026-08
# (Forgejo is the source of truth; the GitHub copy is dead).
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
