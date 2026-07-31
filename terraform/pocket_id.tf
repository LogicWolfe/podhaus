# Pocket ID desired state. People authenticate with passkeys; Terraform
# owns their directory attributes, application access and OIDC claims.
# Existing people are imported below so their user IDs and enrolled
# passkeys survive adoption into Terraform.

data "onepassword_item" "pocket_id_api_key" {
  vault = data.onepassword_vault.homelab.uuid
  title = "Pocket ID API Key"
}

locals {
  forgejo_ssh_key_files = {
    nathan = sort(tolist(fileset("${path.module}/../forgejo/keys/nathan", "*.pub")))
    sky    = sort(tolist(fileset("${path.module}/../forgejo/keys/sky", "*.pub")))
  }

  forgejo_ssh_keys = {
    for username, filenames in local.forgejo_ssh_key_files :
    username => [
      for filename in filenames :
      trimspace(file("${path.module}/../forgejo/keys/${username}/${filename}"))
    ]
  }
}

resource "pocketid_group" "forgejo_users" {
  name          = "forgejo-users"
  friendly_name = "Forgejo users"
}

resource "pocketid_group" "forgejo_admins" {
  name          = "forgejo-admins"
  friendly_name = "Forgejo administrators"
}

resource "pocketid_user" "nathan" {
  username       = "LogicWolfe"
  email          = "nathan@nathanbaxter.com"
  first_name     = "Nathan"
  last_name      = "Baxter"
  display_name   = "Nathan Baxter"
  is_admin       = true
  disabled       = false
  email_verified = false

  groups = [
    pocketid_group.forgejo_users.id,
    pocketid_group.forgejo_admins.id,
  ]

  # Pocket ID interprets a JSON-array custom-claim value as an array in
  # the issued token. Forgejo synchronizes this claim on every login,
  # making removed keys disappear as well as adding new ones.
  custom_claims = {
    ssh_keys = jsonencode(local.forgejo_ssh_keys.nathan)
  }
}

resource "pocketid_user" "sky" {
  username       = "sky"
  email          = "scroeser@gmail.com"
  first_name     = "Sky"
  last_name      = "Croeser"
  display_name   = "Sky Croeser"
  is_admin       = false
  disabled       = false
  email_verified = false

  groups = [
    pocketid_group.forgejo_users.id,
  ]

  custom_claims = {
    ssh_keys = jsonencode(local.forgejo_ssh_keys.sky)
  }
}

resource "pocketid_client" "forgejo" {
  name      = "Forgejo"
  client_id = "forgejo"

  callback_urls = [
    "https://git.pod.haus/user/oauth2/PocketID/callback",
  ]
  logout_callback_urls = [
    "https://git.pod.haus/",
  ]

  launch_url                = "https://git.pod.haus/"
  is_public                 = false
  pkce_enabled              = true
  requires_reauthentication = false

  allowed_user_groups = [
    pocketid_group.forgejo_users.id,
  ]
}

# Forgejo's stack consumes the confidential-client credentials through
# komodo-op. The secret is generated once by Pocket ID, stored in
# Terraform's versioned MinIO state, and copied into 1Password.
resource "onepassword_item" "forgejo_oidc" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Forgejo OIDC"
  category = "login"
  url      = "https://git.pod.haus"
  username = pocketid_client.forgejo.client_id
  password = pocketid_client.forgejo.client_secret
  tags     = ["terraform-managed"]
}

import {
  to = pocketid_user.nathan
  id = "2723e667-4325-4bcb-b91b-ed7442641558"
}

import {
  to = pocketid_user.sky
  id = "55845f16-6433-488a-b1eb-99c438fba147"
}
