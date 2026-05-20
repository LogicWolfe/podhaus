# Cross-root state read: pull the kookaburra relay's reserved IP from
# the relay TF root (terraform/relay.tfstate) so Cloudflare DNS + UniFi
# split-horizon records reference the SAME live value with NO hardcoded
# IPs. When the foundation consolidation lands (one root, see
# terraform-foundation.md), this cross-root read goes away and the same
# data becomes a direct resource reference.

data "terraform_remote_state" "relay" {
  backend = "s3"
  config = {
    endpoints                   = { s3 = "https://storage.pod.haus" }
    bucket                      = "terraform-state"
    key                         = "relay.tfstate"
    region                      = "us-east-1"
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    encrypt                     = false
  }
}
