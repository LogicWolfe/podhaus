variable "account_id" {
  description = "Cloudflare account ID (the one that owns every zone in this repo)"
  type        = string
  default     = "7e660ed6610dce078359713b3cacdea0"
}

variable "minio_user" {
  description = "MinIO root user (TF_VAR_minio_user, from chezmoi → op://Homelab/MinIO Root). Used by the minio provider for admin operations on storage.pod.haus."
  type        = string
  sensitive   = true
}

variable "minio_password" {
  description = "MinIO root password (TF_VAR_minio_password, from chezmoi → op://Homelab/MinIO Root)."
  type        = string
  sensitive   = true
}

# Zone IDs — looked up once with `curl /zones` so resource blocks don't
# have to data-source-lookup each apply. Update if a zone is renamed or
# re-created.
locals {
  zones = {
    "pod.haus"             = "7aa2372eb0cfdba2fe0f2e3bc61aa729"
    "pinelake.haus"        = "460d8e7bd22ba4d45e2d9a4cdadaf427"
    "elusive.email"        = "40dd07b45732564eae016abe8ef68cb0"
    "fractalseed.com"      = "e3e58b53f971b89174351b7af8da92e8"
    "logicaldecay.com"     = "d1d6582fb8920bd732da0c2bbfcf1088"
    "logicaldecay.net"     = "dfc57d04617047e69319e64e52f92579"
    "logicwolfe.com"       = "83d35593a2bd24a2794cdeeca25a0386"
    "nathanbaxter.com"     = "a87330f58f6db1d4e47e0e4ed029494d"
    "nathanbaxter.net"     = "66d58478b39221b80ee2c5ef0202b55b"
    "nathanbaxter.org"     = "8a17b7fa77e6a7b94b4f2f65fd2c86ea"
    "podfoundation.org.au" = "67c381c6b8f1862734cfed38122926af"
    "indigopod.au"         = "a21685ed1bee0bdc7955b728599989ee"
  }

  tunnels = {
    pod_haus = "cc68c7c9-1dad-42aa-af04-46119d3e515f.cfargotunnel.com"
    pinelake = "fec5ca76-b634-4185-bdb2-f85c38b1b570.cfargotunnel.com"
  }

  # Tunnel UUIDs (without the cfargotunnel.com suffix) — needed by the
  # tunnel-config aggregator resource, distinct from the CNAME target.
  tunnel_ids = {
    pod_haus = "cc68c7c9-1dad-42aa-af04-46119d3e515f"
    pinelake = "fec5ca76-b634-4185-bdb2-f85c38b1b570"
  }
}
