# nathanbaxter.com Publii site — bucket + per-site scoped key.
# Pattern is reusable per future Publii tenant (skycroeser.net, …):
# copy this file, swap the name. See docs/plans/nathanbaxter-com-publii.md.

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

# Least-privilege Publii deploy key: read/write that one bucket only
# (ListBucket is required for Publii's files.publii.json deploy delta).
resource "minio_iam_policy" "publii_nathanbaxter_com" {
  name = "publii-nathanbaxter-com"
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

resource "minio_iam_user" "publii_nathanbaxter_com" {
  name = "publii-nathanbaxter-com"
}

resource "minio_iam_user_policy_attachment" "publii_nathanbaxter_com" {
  user_name   = minio_iam_user.publii_nathanbaxter_com.name
  policy_name = minio_iam_policy.publii_nathanbaxter_com.name
}

# Revocable app credential Publii actually uses.
resource "minio_iam_service_account" "publii_nathanbaxter_com" {
  target_user = minio_iam_user.publii_nathanbaxter_com.name
}

output "publii_access_key" {
  value     = minio_iam_service_account.publii_nathanbaxter_com.access_key
  sensitive = true
}

output "publii_secret_key" {
  value     = minio_iam_service_account.publii_nathanbaxter_com.secret_key
  sensitive = true
}
