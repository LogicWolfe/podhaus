# Root credential for the dedicated Pouch-backed MinIO instance. Terraform
# generates it once and 1Password is the handoff to both komodo-op and the
# aliased MinIO provider added below. The standard login fields are deliberate:
# the 1Password data source can resolve their stable username/password IDs.
resource "onepassword_item" "pouch_minio_root" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Pouch MinIO Root"
  category = "login"
  url      = "https://pouch.pod.haus"
  username = "pouch-minio-root"
  tags     = ["terraform-managed"]

  password_recipe {
    length  = 64
    digits  = true
    symbols = true
  }
}

# Sky's repository. Versioning stays disabled: restic owns snapshot history,
# and S3 object versions would keep pruned packs alive indefinitely.
resource "minio_s3_bucket" "sky_backups" {
  provider = minio.pouch

  bucket = "sky-backups"
  acl    = "private"
}

resource "minio_iam_policy" "sky_backups" {
  provider = minio.pouch

  name = "sky-backups"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["arn:aws:s3:::sky-backups/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = ["arn:aws:s3:::sky-backups"]
      },
    ]
  })
}

resource "minio_iam_user" "sky_backups" {
  provider = minio.pouch

  name = "sky-backups"
}

resource "minio_iam_user_policy_attachment" "sky_backups" {
  provider = minio.pouch

  user_name   = minio_iam_user.sky_backups.name
  policy_name = minio_iam_policy.sky_backups.name
}

resource "minio_iam_service_account" "sky_backups" {
  provider = minio.pouch

  target_user = minio_iam_user.sky_backups.name
}

# Read-only metadata identity for the hourly repository monitor. ListBucket is
# enough for mc to see snapshots/<id> names and server-side modification times;
# it cannot read, write, or delete any backup object.
resource "minio_iam_policy" "sky_backups_monitor" {
  provider = minio.pouch

  name = "sky-backups-monitor"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = ["arn:aws:s3:::sky-backups"]
      },
    ]
  })
}

resource "minio_iam_user" "sky_backups_monitor" {
  provider = minio.pouch

  name = "sky-backups-monitor"
}

resource "minio_iam_user_policy_attachment" "sky_backups_monitor" {
  provider = minio.pouch

  user_name   = minio_iam_user.sky_backups_monitor.name
  policy_name = minio_iam_policy.sky_backups_monitor.name
}

resource "minio_iam_service_account" "sky_backups_monitor" {
  provider = minio.pouch

  target_user = minio_iam_user.sky_backups_monitor.name
}

resource "onepassword_item" "sky_backups_monitor" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Sky Backups Monitor"
  category = "login"
  url      = "https://pouch.pod.haus"
  username = minio_iam_service_account.sky_backups_monitor.access_key
  password = minio_iam_service_account.sky_backups_monitor.secret_key
  tags     = ["terraform-managed", "monitoring", "sky"]
}

# One ready-to-use handoff. The standard username/password fields hold the
# S3 access and secret keys; the Restic section carries the repository URL,
# region, and independently-generated repository encryption password.
resource "onepassword_item" "sky_backups" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Sky Backups"
  category = "login"
  url      = "https://pouch.pod.haus"
  username = minio_iam_service_account.sky_backups.access_key
  password = minio_iam_service_account.sky_backups.secret_key
  tags     = ["terraform-managed", "sky"]

  section {
    label = "Restic"

    field {
      label = "RESTIC_REPOSITORY"
      type  = "STRING"
      value = "s3:https://pouch.pod.haus/sky-backups/personal-laptop"
    }

    field {
      label = "RESTIC_PASSWORD"
      type  = "CONCEALED"

      password_recipe {
        length  = 64
        digits  = true
        symbols = true
      }
    }

    field {
      label = "AWS_DEFAULT_REGION"
      type  = "STRING"
      value = "us-east-1"
    }
  }
}

output "sky_backups_repository" {
  value = "s3:https://pouch.pod.haus/sky-backups/personal-laptop"
}
