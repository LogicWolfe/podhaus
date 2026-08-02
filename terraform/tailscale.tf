# Tailscale account configuration and auth-key rotation.
#
# What this owns:
#   1. Tailnet DNS settings used by the podnet management plane.
#   2. A reusable, preauthorized, tag:podnet auth key minted by the
#      tailscale provider via the same OAuth client the tailscale-cleanup
#      init uses.
#   3. An 80-day rotation cadence (time_rotating) that triggers a
#      `terraform plan` to schedule a replace once the window elapses —
#      apply is still explicit (no autopilot).
#   4. A write-back to the existing 1Password item
#      `op://Homelab/Tailscale Auth Key/credential`, so every downstream
#      consumer (kookaburra_bootstrap, the tailscale stacks via
#      komodo-op) picks up the rotated value without code change.
#
# Why local-exec rather than the onepassword_item resource:
#   The 1P item is category API_CREDENTIAL, which the
#   1Password/onepassword TF provider's `onepassword_item` resource does
#   not support (categories limited to login/password/database/secure_note).
#   Re-categorizing risked breaking the `op://.../credential` path that
#   every consumer reads. local-exec keeps the existing item structure
#   intact and uses `op item edit` (already on every machine that runs
#   this root) — TF orchestrates rotation; `op` does the field write.
#   The key value passes via env var (not the command line) so it
#   doesn't surface in Terraform's command-echo logs.
#
# This resource is part of the consolidated podhaus Terraform root.

resource "tailscale_dns_configuration" "podnet" {
  magic_dns          = true
  override_local_dns = false
  search_paths       = []
}

# Recovery is deliberately not a bridged network. Members may reach only SSH
# on tagged recovery nodes; those nodes cannot initiate traffic to anything in
# the tailnet. Host daemons run in userspace mode and publish only local sshd.
resource "tailscale_acl" "podhaus" {
  reset_acl_on_destroy       = false
  overwrite_existing_content = true

  acl = jsonencode({
    tagOwners = {
      "tag:podnet" = ["autogroup:admin"]
      # The Terraform OAuth client is tagged podnet, so it also needs tag
      # ownership to mint the recovery enrolment key.
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
        dst = ["tag:podnet"]
        ip  = ["*"]
      },
      {
        src = ["tag:podnet"]
        dst = ["tag:podnet"]
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
        deny = ["tag:podnet:22", "tag:recovery:22"]
      },
    ]
  })
}

resource "time_rotating" "tailscale_authkey" {
  # 80 days < the Tailscale OAuth-minted key max (90 days). 10-day
  # buffer means a `terraform plan` past day-80 schedules a replace
  # well before the key actually expires. Already-enrolled devices
  # have keyExpiryDisabled set and are unaffected by key expiry; the
  # rotation only matters when a fresh node tries to enrol (e.g. the
  # kookaburra cattle-rebuild path).
  rotation_days = 80
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

resource "tailscale_tailnet_key" "podnet" {
  reusable      = true
  ephemeral     = false
  preauthorized = true
  # Default is 7776000 seconds (90 days); set explicitly for clarity.
  expiry = 7776000
  tags   = ["tag:podnet"]
  # Description on Tailscale's side — alphanumeric only.
  description         = "podnet TF managed"
  recreate_if_invalid = "always"

  lifecycle {
    # Tie to the rotation clock — when time_rotating's id rolls over,
    # next plan schedules this resource for replacement.
    replace_triggered_by = [time_rotating.tailscale_authkey.id]
  }
}

# Write the freshly-minted auth key back into the existing 1P item so
# downstream consumers (kookaburra_bootstrap, komodo-op→tailscale
# stacks) pick it up on their next read. Re-runs only when the key
# resource itself is replaced.
resource "terraform_data" "publish_authkey_to_1password" {
  triggers_replace = [tailscale_tailnet_key.podnet.id]

  provisioner "local-exec" {
    interpreter = ["/bin/sh", "-c"]
    # The key is passed via the NEW_KEY env var, NOT interpolated into
    # the command line — keeps it out of TF's command-echo and the
    # process-list. OP_SERVICE_ACCOUNT_TOKEN is loaded by the PWD hook
    # from the single raw secret allowed on disk.
    command = "op item edit '3yke5rmhs4xpzgkjekvbxptdyu' \"credential=$NEW_KEY\" --vault 'hjpenq2avoprqh2u3hqxap3jjq' >/dev/null"
    environment = {
      NEW_KEY = tailscale_tailnet_key.podnet.key
    }
    quiet = true
  }
}
