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
  }

  backend "s3" {
    endpoints = {
      s3 = "http://minio:9000"
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
