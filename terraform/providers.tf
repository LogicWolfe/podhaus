# Credentials are NOT in HCL and NOT dumped to disk. DIGITALOCEAN_TOKEN
# is read transiently from 1Password into the apply process env
# (op read → env, ephemeral, never persisted) — honoring "only the 1P
# service-account token is ever raw at rest". The foundation plan
# (terraform-foundation.md) replaces this with the onepassword
# provider; that consolidation is the gated, review-first step.
provider "digitalocean" {}
