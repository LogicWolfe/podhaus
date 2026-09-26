# nathanbaxter.com — bucket + per-site scoped deploy key.
# Pattern is reusable per future static-site tenant (skycroeser.net, …):
# copy this file, swap the name.

resource "minio_s3_bucket" "nathanbaxter_com" {
  bucket = "nathanbaxter-com"
  acl    = "private" # public read is granted narrowly by the policy below
}

resource "minio_s3_bucket_versioning" "nathanbaxter_com" {
  bucket = minio_s3_bucket.nathanbaxter_com.bucket
  versioning_configuration {
    status = "Enabled"
  }
}

# Anonymous GetObject ONLY — Caddy serves the rendered site
# anonymously. No anon ListBucket: no public enumeration of unlinked
# objects.
resource "minio_s3_bucket_policy" "nathanbaxter_com" {
  bucket = minio_s3_bucket.nathanbaxter_com.bucket
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadObjects"
      Effect    = "Allow"
      Principal = { AWS = ["*"] }
      Action    = ["s3:GetObject", "s3:GetObjectVersion"]
      Resource  = ["arn:aws:s3:::nathanbaxter-com/*"]
    }]
  })
}

# Least-privilege deploy key: read/write that one bucket only
# (ListBucket is required for clients that compute a deploy delta).
resource "rustfs_policy" "nathanbaxter_com_deploy" {
  name = "nathanbaxter-com-deploy"
  statement = [
    {
      effect    = "Allow"
      action    = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"]
      ressource = ["arn:aws:s3:::nathanbaxter-com/*"]
    },
    {
      effect    = "Allow"
      action    = ["s3:ListBucket", "s3:GetBucketLocation"]
      ressource = ["arn:aws:s3:::nathanbaxter-com"]
    },
  ]
}

resource "rustfs_user" "nathanbaxter_com_deploy" {
  access_key = "nathanbaxter-com-deploy"
  secret_key = random_password.rustfs_user_nathanbaxter_com_deploy.result
  policy     = rustfs_policy.nathanbaxter_com_deploy.name
}

# Revocable app credential the deploy actually uses.
resource "rustfs_serviceaccount" "nathanbaxter_com_deploy" {
  access_key  = "CZRE0QT79G3MU6F5BRDK"
  secret_key  = random_password.rustfs_serviceaccount_nathanbaxter_com_deploy.result
  name        = "nathanbaxter-com-deploy"
  description = ""
  user        = rustfs_user.nathanbaxter_com_deploy.access_key
}

output "nathanbaxter_com_deploy_access_key" {
  value     = rustfs_serviceaccount.nathanbaxter_com_deploy.access_key
  sensitive = true
}

output "nathanbaxter_com_deploy_secret_key" {
  value     = rustfs_serviceaccount.nathanbaxter_com_deploy.secret_key
  sensitive = true
}

# skycroeser-net — Sky Croeser's site (skycroeser.net), served from
# Publii static output. Same shape as nathanbaxter-com above. The
# bucket is named for the real domain even while the site is demoed at
# sky.pod.haus — the temporary host never names storage.
resource "minio_s3_bucket" "skycroeser_net" {
  bucket = "skycroeser-net"
  acl    = "private" # public read is granted narrowly by the policy below
}

resource "minio_s3_bucket_versioning" "skycroeser_net" {
  bucket = minio_s3_bucket.skycroeser_net.bucket
  versioning_configuration {
    status = "Enabled"
  }
}

# Anonymous GetObject ONLY — Caddy serves the rendered site
# anonymously. No anon ListBucket: no public enumeration of unlinked
# objects (e.g. unpublished drafts Publii may stage).
resource "minio_s3_bucket_policy" "skycroeser_net" {
  bucket = minio_s3_bucket.skycroeser_net.bucket
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadObjects"
      Effect    = "Allow"
      Principal = { AWS = ["*"] }
      Action    = ["s3:GetObject", "s3:GetObjectVersion"]
      Resource  = ["arn:aws:s3:::skycroeser-net/*"]
    }]
  })
}

# Least-privilege deploy key for Publii (Sky's laptop): read/write that
# one bucket only (ListBucket is required so Publii can compute the
# deploy delta against files.publii.json). Never the RustFS root creds.
resource "rustfs_policy" "skycroeser_net_deploy" {
  name = "skycroeser-net-deploy"
  statement = [
    {
      effect    = "Allow"
      action    = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"]
      ressource = ["arn:aws:s3:::skycroeser-net/*"]
    },
    {
      effect    = "Allow"
      action    = ["s3:ListBucket", "s3:GetBucketLocation"]
      ressource = ["arn:aws:s3:::skycroeser-net"]
    },
  ]
}

resource "rustfs_user" "skycroeser_net_deploy" {
  access_key = "skycroeser-net-deploy"
  secret_key = random_password.rustfs_user_skycroeser_net_deploy.result
  policy     = rustfs_policy.skycroeser_net_deploy.name
}

# Revocable app credential Publii actually uses. Copy these outputs into
# the 1Password Homelab item for Sky's publish key.
resource "rustfs_serviceaccount" "skycroeser_net_deploy" {
  access_key  = "VQWA4845DIZ3Y3IJ1ALD"
  secret_key  = random_password.rustfs_serviceaccount_skycroeser_net_deploy.result
  name        = "skycroeser-net-deploy"
  description = ""
  user        = rustfs_user.skycroeser_net_deploy.access_key
}

output "skycroeser_net_deploy_access_key" {
  value     = rustfs_serviceaccount.skycroeser_net_deploy.access_key
  sensitive = true
}

output "skycroeser_net_deploy_secret_key" {
  value     = rustfs_serviceaccount.skycroeser_net_deploy.secret_key
  sensitive = true
}

# pets-alive-assets — uploaded art for the pet simulator. NOT publicly
# readable (no anon policy): the pets-alive backend proxies every object
# via /api/assets, so only the scoped service account needs access.
resource "minio_s3_bucket" "pets_alive_assets" {
  bucket = "pets-alive-assets"
  acl    = "private"
}

# Least-privilege: read/write/delete that one bucket. CreateBucket is
# included so the backend's idempotent ensure-bucket-on-boot succeeds
# even on a fresh RustFS instance (it no-ops once this resource has created it).
resource "rustfs_policy" "pets_alive_assets" {
  name = "pets-alive-assets"
  statement = [
    {
      effect    = "Allow"
      action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      ressource = ["arn:aws:s3:::pets-alive-assets/*"]
    },
    {
      effect = "Allow"
      action = [
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:CreateBucket",
      ]
      ressource = ["arn:aws:s3:::pets-alive-assets"]
    },
  ]
}

resource "rustfs_user" "pets_alive_assets" {
  access_key = "pets-alive-assets"
  secret_key = random_password.rustfs_user_pets_alive_assets.result
  policy     = rustfs_policy.pets_alive_assets.name
}

resource "rustfs_serviceaccount" "pets_alive_assets" {
  access_key  = "F0PBY9JEC7NGF2C7RZ5V"
  secret_key  = random_password.rustfs_serviceaccount_pets_alive_assets.result
  name        = "pets-alive-assets"
  description = ""
  user        = rustfs_user.pets_alive_assets.access_key
}

# Copy these two outputs into 1Password (Homelab) item
# "RustFS Pets Alive Assets" with fields ACCESS_KEY_ID / SECRET_ACCESS_KEY
# → OP__KOMODO__RUSTFS_PETS_ALIVE_ASSETS__* (see pets-alive/stack.toml).
output "pets_alive_assets_access_key" {
  value     = rustfs_serviceaccount.pets_alive_assets.access_key
  sensitive = true
}

output "pets_alive_assets_secret_key" {
  value     = rustfs_serviceaccount.pets_alive_assets.secret_key
  sensitive = true
}

# doggos-indigo — Indigo's "Doggos Alive" site, exported from Blocs for
# iPad and published by her over RustFS's SFTP server (see
# docs/runbooks/doggos-indigo.md). Blocs logs in as the scoped IAM user
# directly, so this site has no separate service account.
resource "minio_s3_bucket" "doggos_indigo" {
  bucket = "doggos-indigo"
  acl    = "private" # public read is granted narrowly by the policy below
}

# Versioning is her undo: every publish keeps the file it replaced.
resource "minio_s3_bucket_versioning" "doggos_indigo" {
  bucket = minio_s3_bucket.doggos_indigo.bucket
  versioning_configuration {
    status = "Enabled"
  }
}

resource "minio_s3_bucket_policy" "doggos_indigo" {
  bucket = minio_s3_bucket.doggos_indigo.bucket
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadObjects"
      Effect    = "Allow"
      Principal = { AWS = ["*"] }
      Action    = ["s3:GetObject", "s3:GetObjectVersion"]
      Resource  = ["arn:aws:s3:::doggos-indigo/*"]
    }]
  })
}

resource "rustfs_policy" "doggos_indigo_deploy" {
  name = "doggos-indigo-deploy"
  statement = [
    {
      effect    = "Allow"
      action    = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:DeleteObject"]
      ressource = ["arn:aws:s3:::doggos-indigo/*"]
    },
    {
      effect    = "Allow"
      action    = ["s3:ListBucket", "s3:GetBucketLocation"]
      ressource = ["arn:aws:s3:::doggos-indigo"]
    },
  ]
}

resource "rustfs_user" "doggos_indigo_deploy" {
  access_key = "doggos-indigo-deploy"
  secret_key = random_password.rustfs_user_doggos_indigo_deploy.result
  policy     = rustfs_policy.doggos_indigo_deploy.name
}

# The ready-to-type handoff for Blocs' Publish screen.
resource "onepassword_item" "doggos_indigo_publish" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Doggos Indigo Publish"
  category = "login"
  url      = "https://doggos.indigopod.au"
  username = rustfs_user.doggos_indigo_deploy.access_key
  password = rustfs_user.doggos_indigo_deploy.secret_key
  tags     = ["terraform-managed", "indigo"]

  section {
    label = "Blocs Publish settings"

    field {
      label = "Address"
      type  = "STRING"
      value = "storage.pod.haus"
    }
    field {
      label = "Port"
      type  = "STRING"
      value = "8022"
    }
    field {
      label = "Protocol"
      type  = "STRING"
      value = "SFTP"
    }
    field {
      label = "Path"
      type  = "STRING"
      value = "/doggos-indigo"
    }
    field {
      label = "Reachable from"
      type  = "STRING"
      value = "the home network only"
    }
  }
}

# RustFS's SFTP host key. Generated once here so it never changes across
# redeploys — a changed host key is a scary warning on her iPad.
# Published for komodo-op → OP__KOMODO__SFTP_HOST_KEY__PRIVATE_KEY_B64,
# consumed by rustfs/stack.toml.
resource "tls_private_key" "minio_sftp_host" {
  algorithm = "ED25519"
}

resource "onepassword_item" "minio_sftp_host_key" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "SFTP Host Key"
  category = "secure_note"
  tags     = ["terraform-managed"]

  section_map = {
    Key = {
      field_map = {
        private_key_b64 = {
          type  = "CONCEALED"
          value = base64encode(tls_private_key.minio_sftp_host.private_key_openssh)
        }
        public_key = {
          type  = "STRING"
          value = trimspace(tls_private_key.minio_sftp_host.public_key_openssh)
        }
      }
    }
  }
}
