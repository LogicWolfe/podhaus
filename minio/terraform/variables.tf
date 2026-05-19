variable "minio_user" {
  description = "MinIO root user (TF_VAR_minio_user, from chezmoi → op://Homelab/MinIO Root)."
  type        = string
  sensitive   = true
}

variable "minio_password" {
  description = "MinIO root password (TF_VAR_minio_password, from chezmoi → op://Homelab/MinIO Root)."
  type        = string
  sensitive   = true
}
