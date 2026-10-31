# ClickStack's read-only ClickHouse user for the dashboards (dash). The
# clickstack stack defines the user from this password (its users file reads
# the CLICKHOUSE_EVIDENCE_PASSWORD environment variable) and the dash stack
# presents it; both read the same Homelab item through komodo-op as
# OP__KOMODO__CLICKSTACK_EVIDENCE__PASSWORD.
resource "random_password" "clickstack_evidence" {
  length  = 48
  special = false
}

resource "onepassword_item" "clickstack_evidence" {
  vault    = data.onepassword_vault.homelab.uuid
  title    = "clickstack-evidence"
  category = "password"
  password = random_password.clickstack_evidence.result
  tags     = ["terraform-managed"]
}
