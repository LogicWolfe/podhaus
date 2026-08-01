# Mumble

`voice.pod.haus` is the family Mumble server. Murmur runs on bilby and
accepts direct TCP and UDP traffic on port 64738.

## Traffic path

Mumble doesn't use Cloudflare Tunnel. UDP carries the voice traffic, so the
UDM Pro SE forwards WAN TCP and UDP port 64738 directly to bilby at
`10.0.0.119:64738`.

`voice.pod.haus` is a grey-cloud A record. Terraform owns the record and the
two UniFi port forwards:

- `terraform/dns_voice_pod_haus.tf`
- `terraform/unifi.tf`

The `cloudflare-ddns` stack updates the A record every five minutes because
the home WAN address can change. Terraform ignores changes to the record's
content but still owns its existence and shape.

Murmur terminates its own TLS and creates a self-signed certificate in
`mumble-data` on first start. Clients prompt once to trust it. Caddy and
Cloudflare don't participate in this connection.

## Stack and secrets

The `mumble/` stack uses the official `mumblevoip/mumble-server` image. Its
named `mumble-data` volume holds the SQLite database, registered users,
channel ACLs, and server certificate.

The 1Password Homelab item `MUMBLE` supplies:

- `SUPERUSER_PASSWORD` as
  `OP__KOMODO__MUMBLE__SUPERUSER_PASSWORD`
- `SERVER_PASSWORD` as `OP__KOMODO__MUMBLE__SERVER_PASSWORD`

The server is capped at 20 users with a 72 kbit/s per-user bandwidth limit.

## Monitoring and backup

Gatus probes `tcp://voice.pod.haus:64738`. This covers public DNS, the TCP
port forward, bilby's firewall, and Murmur's control listener. It doesn't
prove UDP voice quality, so test an actual call after changing the network or
port-forward configuration.

Backrest backs up the `mumble-data` volume nightly under the `mumble` plan.
That backup is the recovery source for the database and the certificate that
clients already trust.

## Operations

- Deploy configuration changes through the normal push procedure or
  `./komodo-sync`.
- Check `docker logs mumble` for client, TLS, and authentication failures.
- Check `docker logs cloudflare-ddns` if `voice.pod.haus` no longer resolves
  to the current WAN address.
- Restore `mumble-data` before starting Murmur on a rebuilt host. Starting
  with an empty volume creates a new certificate and loses registered users
  and ACLs.
