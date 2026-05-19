output "reserved_ip" {
  description = "Stable public IP for kookaburra — the storage.pod.haus A-record target (set in the cloudflare/ root at DNS cutover)."
  value       = digitalocean_reserved_ip.kookaburra.ip_address
}

output "droplet_ipv4" {
  description = "kookaburra's own droplet IPv4 (for the SSH Periphery bootstrap)."
  value       = digitalocean_droplet.kookaburra.ipv4_address
}
