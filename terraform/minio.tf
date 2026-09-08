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
      Action    = ["s3:GetObject"]
      Resource  = ["arn:aws:s3:::nathanbaxter-com/*"]
    }]
  })
}

# Least-privilege deploy key: read/write that one bucket only
# (ListBucket is required for clients that compute a deploy delta).
resource "minio_iam_policy" "nathanbaxter_com_deploy" {
  name = "nathanbaxter-com-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::nathanbaxter-com/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = ["arn:aws:s3:::nathanbaxter-com"]
      },
    ]
  })
}

resource "minio_iam_user" "nathanbaxter_com_deploy" {
  name = "nathanbaxter-com-deploy"
}

resource "minio_iam_user_policy_attachment" "nathanbaxter_com_deploy" {
  user_name   = minio_iam_user.nathanbaxter_com_deploy.name
  policy_name = minio_iam_policy.nathanbaxter_com_deploy.name
}

# Revocable app credential the deploy actually uses.
resource "minio_iam_service_account" "nathanbaxter_com_deploy" {
  target_user = minio_iam_user.nathanbaxter_com_deploy.name
}

output "nathanbaxter_com_deploy_access_key" {
  value     = minio_iam_service_account.nathanbaxter_com_deploy.access_key
  sensitive = true
}

output "nathanbaxter_com_deploy_secret_key" {
  value     = minio_iam_service_account.nathanbaxter_com_deploy.secret_key
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
      Action    = ["s3:GetObject"]
      Resource  = ["arn:aws:s3:::skycroeser-net/*"]
    }]
  })
}

# Least-privilege deploy key for Publii (Sky's laptop): read/write that
# one bucket only (ListBucket is required so Publii can compute the
# deploy delta against files.publii.json). Never the MinIO root creds.
resource "minio_iam_policy" "skycroeser_net_deploy" {
  name = "skycroeser-net-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::skycroeser-net/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = ["arn:aws:s3:::skycroeser-net"]
      },
    ]
  })
}

resource "minio_iam_user" "skycroeser_net_deploy" {
  name = "skycroeser-net-deploy"
}

resource "minio_iam_user_policy_attachment" "skycroeser_net_deploy" {
  user_name   = minio_iam_user.skycroeser_net_deploy.name
  policy_name = minio_iam_policy.skycroeser_net_deploy.name
}

# Revocable app credential Publii actually uses. Copy these outputs into
# the 1Password Homelab item for Sky's publish key.
resource "minio_iam_service_account" "skycroeser_net_deploy" {
  target_user = minio_iam_user.skycroeser_net_deploy.name
}

output "skycroeser_net_deploy_access_key" {
  value     = minio_iam_service_account.skycroeser_net_deploy.access_key
  sensitive = true
}

output "skycroeser_net_deploy_secret_key" {
  value     = minio_iam_service_account.skycroeser_net_deploy.secret_key
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
# even on a fresh MinIO (it no-ops once this resource has created it).
resource "minio_iam_policy" "pets_alive_assets" {
  name = "pets-alive-assets"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::pets-alive-assets/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:CreateBucket",
        ]
        Resource = ["arn:aws:s3:::pets-alive-assets"]
      },
    ]
  })
}

resource "minio_iam_user" "pets_alive_assets" {
  name = "pets-alive-assets"
}

resource "minio_iam_user_policy_attachment" "pets_alive_assets" {
  user_name   = minio_iam_user.pets_alive_assets.name
  policy_name = minio_iam_policy.pets_alive_assets.name
}

resource "minio_iam_service_account" "pets_alive_assets" {
  target_user = minio_iam_user.pets_alive_assets.name
}

# Copy these two outputs into 1Password (Homelab) item
# "MINIO Pets Alive Assets" with fields ACCESS_KEY_ID / SECRET_ACCESS_KEY
# → OP__KOMODO__MINIO_PETS_ALIVE_ASSETS__* (see pets-alive/stack.toml).
output "pets_alive_assets_access_key" {
  value     = minio_iam_service_account.pets_alive_assets.access_key
  sensitive = true
}

output "pets_alive_assets_secret_key" {
  value     = minio_iam_service_account.pets_alive_assets.secret_key
  sensitive = true
}

# doggos-indigo — Indigo's "Doggos Alive" site, exported from Blocs for
# iPad and published by her over MinIO's SFTP server (see
# docs/runbooks/doggos-indigo.md). Same shape as the two sites above,
# minus the service account: Blocs logs in as the IAM user itself, since
# a service account needs "=svc" appended to the username, which is a
# footgun on an iPad keyboard.
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
      Action    = ["s3:GetObject"]
      Resource  = ["arn:aws:s3:::doggos-indigo/*"]
    }]
  })
}

resource "minio_iam_policy" "doggos_indigo_deploy" {
  name = "doggos-indigo-deploy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::doggos-indigo/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = ["arn:aws:s3:::doggos-indigo"]
      },
    ]
  })
}

resource "minio_iam_user" "doggos_indigo_deploy" {
  name = "doggos-indigo-deploy"
}

resource "minio_iam_user_policy_attachment" "doggos_indigo_deploy" {
  user_name   = minio_iam_user.doggos_indigo_deploy.name
  policy_name = minio_iam_policy.doggos_indigo_deploy.name
}

# The ready-to-type handoff for Blocs' Publish screen.
resource "onepassword_item" "doggos_indigo_publish" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Doggos Indigo Publish"
  category = "login"
  url      = "https://doggos.indigopod.au"
  username = minio_iam_user.doggos_indigo_deploy.name
  password = minio_iam_user.doggos_indigo_deploy.secret
  tags     = ["terraform-managed", "indigo"]

  section {
    label = "Blocs Publish settings"

    field {
      label = "Address"
      type  = "STRING"
      value = "bilby.pod.haus"
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

# MinIO's SFTP host key. Generated once here so it never changes across
# redeploys — a changed host key is a scary warning on her iPad.
# Published for komodo-op → OP__KOMODO__MINIO_SFTP_HOST_KEY__PRIVATE_KEY_B64,
# consumed by minio/stack.toml.
resource "tls_private_key" "minio_sftp_host" {
  algorithm = "ED25519"
}

resource "onepassword_item" "minio_sftp_host_key" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "MinIO SFTP Host Key"
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
