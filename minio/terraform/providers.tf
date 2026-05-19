# The MinIO admin API (used for IAM resources) is served on
# storage.pod.haus alongside S3 — Caddy proxies the full API and the
# access-control boundary is MinIO SigV4 (there is deliberately NO
# /minio/admin/ edge block; one would break this root, and no TF root
# is exempt from the from-anywhere rule). Provider auths as MinIO
# root (Terraform needs full reach; a scoped admin cred is
# escalation-capable anyway). Creds from the chezmoi-rendered fish env
# (TF_VAR_minio_*, op://Homelab/MinIO Root).
provider "minio" {
  minio_server   = "storage.pod.haus"
  minio_ssl      = true
  minio_region   = "us-east-1"
  minio_user     = var.minio_user
  minio_password = var.minio_password
}
