# These addresses retain the existing credentials and SFTP host key in state.
moved {
  from = onepassword_item.pouch_minio_root
  to   = onepassword_item.pouch_rustfs_root
}

moved {
  from = tls_private_key.minio_sftp_host
  to   = tls_private_key.rustfs_sftp_host
}

moved {
  from = onepassword_item.minio_sftp_host_key
  to   = onepassword_item.rustfs_sftp_host_key
}
