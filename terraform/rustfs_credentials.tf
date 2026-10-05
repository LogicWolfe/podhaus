# RustFS's native provider requires caller-supplied secrets for users and
# service accounts. Those spelling out every attribute were imported with the
# credentials already in use; prevent_destroy makes accidental regeneration fail.

resource "random_password" "rustfs_user_nathanbaxter_com_deploy" {
  length      = 56
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_user_skycroeser_net_deploy" {
  length      = 56
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_user_pets_alive_assets" {
  length      = 56
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_user_doggos_indigo_deploy" {
  length      = 56
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_user_sky_backups" {
  length      = 56
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_user_sky_backups_monitor" {
  length      = 56
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_serviceaccount_nathanbaxter_com_deploy" {
  length      = 40
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_serviceaccount_skycroeser_net_deploy" {
  length      = 40
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_serviceaccount_pets_alive_assets" {
  length      = 40
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_serviceaccount_sky_backups" {
  length      = 40
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_serviceaccount_sky_backups_monitor" {
  length      = 40
  lower       = true
  min_lower   = 0
  min_numeric = 0
  min_special = 0
  min_upper   = 0
  number      = true
  numeric     = true
  special     = true
  upper       = true

  lifecycle {
    prevent_destroy = true
  }
}

# Alphanumeric: Fenwick's secret reaches its container through Komodo's .env
# and Compose interpolation, which would expand a "$".
resource "random_password" "rustfs_user_fenwick" {
  length  = 56
  special = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "rustfs_serviceaccount_fenwick" {
  length  = 40
  special = false

  lifecycle {
    prevent_destroy = true
  }
}
