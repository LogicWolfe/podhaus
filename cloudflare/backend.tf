terraform {
  required_version = ">= 1.10.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    unifi = {
      # Community fork — the upstream paultyng/unifi provider doesn't
      # expose a dns_record resource. ubiquiti-community has feature
      # parity plus the UniFi DNS records the controller added more
      # recently.
      # Docs: https://registry.terraform.io/providers/ubiquiti-community/unifi/latest/docs
      source  = "ubiquiti-community/unifi"
      version = "~> 0.41"
    }
    github = {
      # Used only for the Komodo deploy webhook on LogicWolfe/podhaus.
      # Docs: https://registry.terraform.io/providers/integrations/github/latest/docs
      source  = "integrations/github"
      version = "~> 6.0"
    }
    tailscale = {
      # Mints the rotating tag:podnet tailnet auth key. Interim home —
      # will move to the consolidated TF root (see
      # docs/plans/terraform-foundation.md) via state mv when that lands.
      # Docs: https://registry.terraform.io/providers/tailscale/tailscale/latest/docs
      source  = "tailscale/tailscale"
      version = "~> 0.21"
    }
    time = {
      # Drives the 80-day rotation cadence for the tailnet auth key.
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }

  backend "s3" {
    endpoints = {
      # Public endpoint so Terraform runs from any machine. Path goes
      # storage.pod.haus → (split-horizon on LAN / WAN port-forward
      # off-LAN) → Caddy (own LE cert) → MinIO. Caddy forwards the
      # SigV4-signed Accept-Encoding/Host unchanged, so the aws-sdk-go
      # signature validates — the whole reason this is not Cloudflare-
      # proxied. See docs/plans/minio-public-caddy.md.
      s3 = "https://storage.pod.haus"
    }
    bucket                      = "terraform-state"
    key                         = "cloudflare.tfstate"
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
