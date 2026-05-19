# NOTE (overnight build): this is the relay's own root/state for now.
# The foundation plan (terraform-foundation.md) consolidates
# cloudflare/ + minio/terraform/ + this into ONE root with the
# onepassword provider — that migration is the gated, review-first
# step and is deliberately NOT executed unattended. Keeping relay
# state separate tonight avoids blind state surgery on live roots.
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }

  backend "s3" {
    endpoints                   = { s3 = "https://storage.pod.haus" }
    bucket                      = "terraform-state"
    key                         = "relay.tfstate"
    region                      = "us-east-1"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    use_lockfile                = true
    encrypt                     = false
  }
}
