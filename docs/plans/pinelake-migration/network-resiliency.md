# Pinelake network resilience

Pinelake will not join the podhaus tailnet and will not expose a subnet route.
The host remains outbound-only:

- Periphery dials `core-connect.pod.haus` with Komodo Noise authentication.
- Alloy sends to `logs-ingest.pod.haus` with per-host mTLS.
- Browser and SSH endpoints get individual rathole services only when required.

This keeps a compromised gateway from gaining general reachability into
Pinelake. The cost is that Numbat or the internet path is a dependency for
remote management. Local console and LAN SSH remain recovery paths.

Verification is a reboot with no interactive login, healthy Periphery and Alloy
connections, working named routes, and failure of every unconfigured inbound
port and cross-host destination.
