# Root credential for the dedicated Pouch-backed RustFS instance. Terraform
# generates it once and 1Password is the handoff to both komodo-op and the
# aliased providers. The standard login fields are deliberate:
# the 1Password data source can resolve their stable username/password IDs.
resource "onepassword_item" "pouch_minio_root" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Pouch RustFS Root"
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

resource "rustfs_policy" "sky_backups" {
  provider = rustfs.pouch

  name = "sky-backups"
  statement = [
    {
      effect    = "Allow"
      action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      ressource = ["arn:aws:s3:::sky-backups/*"]
    },
    {
      effect    = "Allow"
      action    = ["s3:ListBucket", "s3:GetBucketLocation"]
      ressource = ["arn:aws:s3:::sky-backups"]
    },
  ]
}

resource "rustfs_user" "sky_backups" {
  provider = rustfs.pouch

  access_key = "sky-backups"
  secret_key = random_password.rustfs_user_sky_backups.result
  policy     = rustfs_policy.sky_backups.name
}

resource "rustfs_serviceaccount" "sky_backups" {
  provider = rustfs.pouch

  access_key  = "6AMTJ3T0GM1BT4A6C4IB"
  secret_key  = random_password.rustfs_serviceaccount_sky_backups.result
  name        = "sky-backups"
  description = ""
  user        = rustfs_user.sky_backups.access_key
}

# Read-only metadata identity for the hourly repository monitor. ListBucket is
# enough for mc to see snapshots/<id> names and server-side modification times;
# it cannot read, write, or delete any backup object.
resource "rustfs_policy" "sky_backups_monitor" {
  provider = rustfs.pouch

  name = "sky-backups-monitor"
  statement = [
    {
      effect    = "Allow"
      action    = ["s3:ListBucket", "s3:GetBucketLocation"]
      ressource = ["arn:aws:s3:::sky-backups"]
    },
  ]
}

resource "rustfs_user" "sky_backups_monitor" {
  provider = rustfs.pouch

  access_key = "sky-backups-monitor"
  secret_key = random_password.rustfs_user_sky_backups_monitor.result
  policy     = rustfs_policy.sky_backups_monitor.name
}

resource "rustfs_serviceaccount" "sky_backups_monitor" {
  provider = rustfs.pouch

  access_key  = "WNPK54SZAR1N363YD04F"
  secret_key  = random_password.rustfs_serviceaccount_sky_backups_monitor.result
  name        = "sky-backups-monitor"
  description = ""
  user        = rustfs_user.sky_backups_monitor.access_key
}

resource "onepassword_item" "sky_backups_monitor" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "Sky Backups Monitor"
  category = "login"
  url      = "https://pouch.pod.haus"
  username = rustfs_serviceaccount.sky_backups_monitor.access_key
  password = rustfs_serviceaccount.sky_backups_monitor.secret_key
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
  username = rustfs_serviceaccount.sky_backups.access_key
  password = rustfs_serviceaccount.sky_backups.secret_key
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
