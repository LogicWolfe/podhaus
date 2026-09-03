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
    pocketid_group.forgejo_users.id,
    pocketid_group.pomerium_users.id,
    pocketid_group.yiayia_editors.id,
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
# Terraform's versioned MinIO state, and copied into 1Password.
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
