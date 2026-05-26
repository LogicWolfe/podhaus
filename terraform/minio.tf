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
