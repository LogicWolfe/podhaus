# Numbat retirement gate

Numbat/Pomerium, Cloudflare caching, Kangaroo SSH, and the host-native
Tailscale recovery plane are implemented. Current operation is documented in
[Networking](/networking.html), [Hosts](/hosts.html),
[Terraform](/terraform.html), [Monitoring](/monitoring.html), and
[Public site caching](/caching.md).

Kookaburra, Cloudflare Tunnel and Access, Cloudflare browser SSH, and the old
<code>tag:podnet</code> route remain live only for rollback. Remove them only
after Nathan independently verifies the active system and explicitly approves
retirement. Then update the Pinelake plan to use the proven Numbat contract and
delete this plan.
