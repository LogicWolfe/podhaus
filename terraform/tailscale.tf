# Tailscale is an SSH-only recovery plane. Host-native userspace daemons
# publish local OpenSSH on port 22 without installing routes or DNS on hosts.
resource "tailscale_dns_configuration" "tailnet" {
  magic_dns          = true
  override_local_dns = false
  search_paths       = []
}

resource "tailscale_acl" "podhaus" {
  reset_acl_on_destroy       = false
  overwrite_existing_content = true

  acl = jsonencode({
    tagOwners = {
      # Terraform's broad OAuth client carries this legacy credential tag.
      # Declaring ownership keeps the client usable; no grant names the tag.
      "tag:podnet" = ["autogroup:admin"]
      # The Terraform OAuth client is tagged podnet and needs ownership to
      # mint recovery enrolment keys. The tag has no network grants.
      "tag:recovery" = ["autogroup:admin", "tag:podnet"]
    }
    grants = [
      {
        src = ["autogroup:member"]
        dst = ["autogroup:member"]
        ip  = ["*"]
      },
      {
        src = ["autogroup:member"]
        dst = ["tag:recovery"]
        ip  = ["tcp:22"]
      },
    ]
    ssh = [{
      action = "check"
      src    = ["autogroup:member"]
      dst    = ["autogroup:self"]
      users  = ["autogroup:nonroot", "root"]
    }]
    tests = [
      {
        src    = "nathan@nathanbaxter.com"
        accept = ["tag:recovery:22"]
        deny   = ["tag:recovery:80"]
      },
      {
        src  = "tag:recovery"
        deny = ["tag:recovery:22"]
      },
      {
        src  = "tag:podnet"
        deny = ["tag:recovery:22"]
      },
    ]
  })
}

resource "time_rotating" "tailscale_recovery_authkey" {
  rotation_days = 80
}

resource "tailscale_tailnet_key" "recovery" {
  reusable            = true
  ephemeral           = false
  preauthorized       = true
  expiry              = 7776000
  tags                = ["tag:recovery"]
  description         = "recovery TF managed"
  recreate_if_invalid = "always"

  lifecycle {
    replace_triggered_by = [time_rotating.tailscale_recovery_authkey.id]
  }
}

resource "onepassword_item" "tailscale_recovery_authkey" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Tailscale Recovery Auth Key"
  category = "login"
  username = "tag:recovery"
  password = tailscale_tailnet_key.recovery.key
  tags     = ["terraform-managed"]
}
