# Pocket ID desired state. People authenticate with passkeys; Terraform
# owns their directory attributes, application access and OIDC claims.
# Existing people were imported (not created) so their user IDs and
# enrolled passkeys survived adoption into Terraform.

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

resource "pocketid_group" "tailscale_users" {
  name          = "tailscale-users"
  friendly_name = "Tailscale users"
}

# Who may edit Yiayia's stories. The app never holds a list of emails; this
# group is the whole of it.
resource "pocketid_group" "yiayia_editors" {
  name          = "yiayia-editors"
  friendly_name = "Yiayia's stories editors"
}

# Who the protected routes in pomerium/config.yaml let through. Pomerium
# reads group names from the `groups` claim of the sign-in token, so
# membership here is the whole of each list: family routes allow `family`,
# friends routes allow `family` or `friends`.
resource "pocketid_group" "family" {
  name          = "family"
  friendly_name = "Family"
}

resource "pocketid_group" "friends" {
  name          = "friends"
  friendly_name = "Friends"
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
    pocketid_group.family.id,
    pocketid_group.forgejo_users.id,
    pocketid_group.forgejo_admins.id,
    pocketid_group.pomerium_users.id,
    pocketid_group.tailscale_users.id,
    pocketid_group.yiayia_editors.id,
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
    pocketid_group.family.id,
    pocketid_group.forgejo_users.id,
    pocketid_group.pomerium_users.id,
    pocketid_group.yiayia_editors.id,
  ]

  custom_claims = {
    ssh_keys = jsonencode(local.forgejo_ssh_keys.sky)
  }
}

# Indigo's identity exists for the family Pomerium routes and nothing else:
# no Forgejo account, so no `ssh_keys` claim and no forgejo-users membership.
# `last_name` is set because Pocket ID answers with an empty string for an
# unset surname, which the provider reports as an inconsistent apply result
# when the attribute is absent from config.
resource "pocketid_user" "indigo" {
  username       = "indigo"
  email          = "indigo@indigopod.au"
  first_name     = "Indigo"
  last_name      = ""
  is_admin       = false
  disabled       = false
  email_verified = false

  groups = [
    pocketid_group.family.id,
    pocketid_group.pomerium_users.id,
  ]
}

# A friend: the friends routes and a Forgejo account. No `ssh_keys` claim,
# so Forgejo synchronizes no keys for him.
resource "pocketid_user" "alex" {
  username       = "alex"
  email          = "alex@louden.com"
  first_name     = "Alex"
  last_name      = "Louden"
  display_name   = "Alex Louden"
  is_admin       = false
  disabled       = false
  email_verified = false

  groups = [
    pocketid_group.forgejo_users.id,
    pocketid_group.friends.id,
    pocketid_group.pomerium_users.id,
  ]
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

# yiayia.pod.haus is its own OpenID Connect client: public, PKCE, no secret.
# The app trusts any ID token issued to this client, so membership of the
# editors group is what decides who may edit.
resource "pocketid_client" "yiayia_stories" {
  name      = "Yiayia's stories"
  client_id = "yiayia-stories"

  callback_urls = [
    "https://yiayia.pod.haus/sign-in/callback",
  ]
  logout_callback_urls = [
    "https://yiayia.pod.haus/",
  ]

  launch_url                = "https://yiayia.pod.haus/"
  is_public                 = true
  pkce_enabled              = true
  requires_reauthentication = false

  allowed_user_groups = [
    pocketid_group.yiayia_editors.id,
  ]
}

# The client of the llm.pod.haus token command (llm/client/llm_token.py),
# which signs people in with Pocket ID's device grant and hands the access
# token to pi or Claude Code as their API key, and of the setup page at
# https://llm.pod.haus/setup/, which signs people in from the browser with the
# authorization-code grant and PKCE and shows the same kind of token. Public,
# because neither can keep a secret. The setup page is the one callback a
# browser sign-in returns to.
# Limited to the two groups the llm.pod.haus route admits, so Pocket ID itself
# refuses anyone else at approval and at every hourly renewal.
resource "pocketid_client" "llm_token" {
  name      = "llm.pod.haus"
  client_id = "llm-token"

  callback_urls = [
    "https://llm.pod.haus/setup/",
  ]

  is_public                 = true
  pkce_enabled              = true
  requires_reauthentication = false

  allowed_user_groups = [
    pocketid_group.family.id,
    pocketid_group.friends.id,
  ]
}

resource "pocketid_client" "tailscale" {
  name      = "Tailscale"
  client_id = "tailscale"

  callback_urls = [
    "https://login.tailscale.com/a/oauth_response",
  ]

  is_public                 = false
  pkce_enabled              = false
  requires_reauthentication = false

  allowed_user_groups = [
    pocketid_group.tailscale_users.id,
  ]
}

# Forgejo's stack consumes the confidential-client secret through
# komodo-op. The secret is generated once by Pocket ID, stored in
# Terraform's versioned RustFS state, and copied into 1Password.
#
# No username field, deliberately: komodo-op syncs every field as a
# secret Komodo Variable, and Komodo redacts every secret's value in
# stored deploy state. A variable whose value is the literal "forgejo"
# rewrites that string inside the forgejo stack's deployed_services
# (service/container/image names), which breaks the name match against
# running containers and pins the stack at state "down" forever. The
# client id is not a secret; it lives as a literal in forgejo/stack.toml
# and in pocketid_client.forgejo above.
resource "onepassword_item" "forgejo_oidc" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Forgejo OIDC"
  category = "login"
  url      = "https://git.pod.haus"
  password = pocketid_client.forgejo.client_secret
  tags     = ["terraform-managed"]
}

resource "onepassword_item" "tailscale_oidc" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Tailscale OIDC"
  category = "login"
  url      = "https://login.tailscale.com"
  username = pocketid_client.tailscale.client_id
  password = pocketid_client.tailscale.client_secret
  tags     = ["terraform-managed"]
}
