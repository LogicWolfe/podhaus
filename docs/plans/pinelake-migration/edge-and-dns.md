# Pinelake edge and DNS

Pinelake will not run cloudflared.

For each intentionally exposed service, Pinelake makes a named outbound rathole
connection to Numbat. Protected browser routes terminate at Pomerium and use
Pocket ID's Nathan-only policy. Machine endpoints keep their protocol-specific
application credential. Cloudflare remains authoritative DNS, with DNS-only
records to Numbat.

Terraform owns DNS, Pomerium/Pocket ID resources, rathole tokens, and 1Password
handoffs in the existing consolidated root. Do not create a Pinelake-specific
Terraform root or a broad service token.

Verify each route from off-LAN, prove that an unlisted host or path fails, and
confirm stopping the Pinelake rathole client affects only its named services.
