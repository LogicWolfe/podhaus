# Bandicoot onboarding

Bandicoot is an Apple Silicon MacBook Pro running Fedora Asahi Remix 44 with
16 KiB kernel pages. It joined on 2026-09-09 as a runtime and development host.
No existing services move in this work, and backup waits for the later stateful
migration. The steady-state description lives in `docs/hosts.html#bandicoot`.

Done and verified:
- Ansible: `playbooks/bandicoot.yml` applied over the split-horizon name, second
  run `changed=0`. Base role laptop policy (lid/idle/sleep) and USB autosuspend
  exemption for the dock NIC. firewalld on bilby's public zone.
- Terraform: log-ingest certificate, rathole tokens, Pomerium routes, docs DNS,
  UniFi reservation for the USB adapter (10.0.0.90), split-horizon
  `bandicoot.pod.haus`, machine key to GitHub and the Pocket ID `ssh_keys` claim.
- Komodo: server Ok; bandicoot-logging, -autoheal, -relay, -caddy and -docs
  running. Logs in ClickStack with `host=bandicoot`.
- chezmoi applied (headless, LAN routing auto); machine key on the YubiKey 5C
  PIV slot 9a, served by machine-ssh-agent; fleet.toml entry pushed.
- Bootstrap key retired: bilby-only grant removed, hand-written
  authorized_keys files removed on both hosts.

Remaining:
- The GitHub SSH *signing* key registration is out-of-band (as for every fleet
  machine key).
- Other homelab targets (fractal, voltaire, numbat, pinelake) admit bandicoot's
  key on their next `--tags ssh` playbook run.
- Remove this plan once the above is done.

Done since the first draft: `op-vault mint dev` enrolled (file backend, on
bilby's terms); full `chezmoi apply` converges; Forgejo synced the machine
key from the Pocket ID claim; `fj` is authenticated; git pushes from
bandicoot to git.pod.haus and github.com unattended.
