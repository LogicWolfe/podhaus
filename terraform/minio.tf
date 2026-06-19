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
