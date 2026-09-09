# Bandicoot onboarding

Bandicoot is an Apple Silicon MacBook Pro running Fedora Asahi Remix 44 with
16 KiB kernel pages. It joins as a runtime and development host. No existing
services move in this work, and backup waits for the later stateful migration.

Done so far: hostname and bootstrap SSH established; Terraform created the
log-ingest certificate, docs DNS and SSH/HTTP relay tokens. Komodo's secret
sync confirmed all four new credential fields. Core trusts its new Periphery key.

Remaining:
- Converge Ansible and verify Core Ok, all five stacks, log ingestion and docs.
- Connect the USB Ethernet adapter; reserve its MAC in UniFi and add SSH-only
  split-horizon DNS. Wi-Fi 10.0.0.237 is the temporary Ansible transport.
- Confirm the host_vars-gated laptop power policy with Nathan.
- Apply chezmoi and register id_bandicoot across Forgejo, GitHub and fleet SSH.
  /home is unencrypted; Nathan must decide encryption or a documented exception.
  The bootstrap id_ed25519 grant remains bilby-only until the final identity lands.
- Confirm Homelab read access and have Nathan enrol the development service account.
- Verify LAN pinned SSH, off-LAN Pomerium SSH, unattended Git push and changed=0.
- Fold completed state into the host documentation and remove this plan.

Operational evidence and intermediate logs are in Nathan's home on bilby:
`bandicoot-onboarding-notes.md`, `bandicoot-terraform-plan.log`,
`bandicoot-terraform-apply.log`, and `bandicoot-ansible-*.log`.
