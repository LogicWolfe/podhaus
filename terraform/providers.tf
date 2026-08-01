# Provider configurations for the consolidated podhaus root.
#
# Credentials come from the PWD-scoped chezmoi-rendered fish env
# (~/.config/fish/conf.d/podhaus-tf.fish, loaded by the
# __podhaus_tf_load function on cd into ~/repos/podhaus). All values
# resolve from 1Password's Homelab vault. The 1P service-account
# token is the ONE secret raw on disk (see AGENTS.md); MinIO bucket
# creds (AWS_*) are least-priv-scoped to the terraform-state bucket;
# the remaining ambient credentials are tracked as deferred platform debt in
# docs/plans/alligator-bilby-migration/deferred-followups.md.

provider "cloudflare" {
  # api_token from CLOUDFLARE_API_TOKEN env var (chezmoi-rendered).
}

provider "unifi" {
  # Reach the controller via its public tunnel hostname (module.unifi
  # publishes unifi.pod.haus → the controller), so Terraform runs from
  # any machine, not just the LAN. api_key from UNIFI_API_KEY env.
  # The tunnel presents a valid Cloudflare edge cert, so no
  # allow_insecure needed.
  api_url = "https://unifi.pod.haus"
}

provider "github" {
  owner = "LogicWolfe"
  # token from GITHUB_TOKEN env var.
}

provider "tailscale" {
  # OAuth client credentials from TAILSCALE_OAUTH_CLIENT_ID /
  # TAILSCALE_OAUTH_CLIENT_SECRET env vars. Same OAuth client the
  # tailscale-cleanup init uses; scope auth_keys:write mints the
  # rotating tailnet key. tailnet arg omitted — defaults to the
  # tailnet that owns the OAuth client.
}

provider "digitalocean" {
  # token from DIGITALOCEAN_TOKEN env var.
}

provider "minio" {
  # MinIO admin API (for IAM resources) is served on storage.pod.haus
  # alongside S3 — Caddy proxies the full API; SigV4 is the boundary.
  # Provider auths as MinIO root (full reach; scoped admin creds are
  # escalation-capable anyway). Creds from TF_VAR_minio_user /
  # TF_VAR_minio_password env vars (op://Homelab/MinIO Root).
  minio_server   = "storage.pod.haus"
  minio_ssl      = true
  minio_region   = "us-east-1"
  minio_user     = var.minio_user
  minio_password = var.minio_password
}

# Standard login fields make this newly-created root credential readable by
# the 1Password data source. The aliased provider reaches the full admin API
# through the public endpoint, preserving the from-any-machine TF contract.
data "onepassword_item" "pouch_minio_root" {
  vault = data.onepassword_vault.homelab.uuid
  title = onepassword_item.pouch_minio_root.title

  depends_on = [onepassword_item.pouch_minio_root]
}

provider "minio" {
  alias = "pouch"

  minio_server   = "pouch.pod.haus"
  minio_ssl      = true
  minio_region   = "us-east-1"
  minio_user     = data.onepassword_item.pouch_minio_root.username
  minio_password = data.onepassword_item.pouch_minio_root.password
}

# The 1Password TF provider was scaffolded here as part of the
# foundation consolidation. It works, BUT the existing Homelab vault
# items (Cloudflare API Token, UniFi API Key, MinIO Root, Komodo
# Webhook Secret, Tailscale OAuth Client, GitHub PAT, DigitalOcean PAT)
# all use root-level fields with random UUIDs as field IDs — and the
# data source's top-level attribute mapping switches on f.ID against
# a small fixed set (username/password/credential/hostname/…). So the
# data source returns empty for every cred we'd want to swap, unless
# the items get restructured to either put fields in sections (and we
# read via section_map[…].field_map[…].value) or recreated with
# expected field IDs. That restructure ripples to chezmoi `op read`
# paths, komodo-op slugified Komodo Variables, and any stack.toml
# `[[OP__…]]` refs. Deferred; see /docs/terraform.html.
#
# The resolvable exceptions use fields the provider understands:
# access.tf reads Pocket ID's sectioned OIDC fields, while
# pocket_id.tf reads the API Credential item and manages the Forgejo
# Login item.

provider "pocketid" {
  # Public by design: OIDC relying parties and Terraform must reach the
  # issuer without Cloudflare Access in front. The API token is resolved
  # from 1Password at plan time and never committed.
  base_url  = "https://id.pod.haus"
  api_token = data.onepassword_item.pocket_id_api_key.credential
}
