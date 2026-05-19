terraform {
  required_version = ">= 1.10.0"

  required_providers {
    minio = {
      # Docs: https://registry.terraform.io/providers/aminueza/minio/latest/docs
      source  = "aminueza/minio"
      version = "~> 3.0"
    }
  }

  # State alongside cloudflare.tfstate, separate key. Reached over the
  # public storage.pod.haus like every other root — this root is
  # from-anywhere too (NO TF root is exempt; see AGENTS.md). Lockfile
  # is not committed (each machine self-locks).
  backend "s3" {
    endpoints = {
      s3 = "https://storage.pod.haus"
    }
    bucket                      = "terraform-state"
    key                         = "minio.tfstate"
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
