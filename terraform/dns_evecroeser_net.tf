# evecroeser.net — Eve's domain. INTENTIONALLY EMPTY (no records).
#
# The domain has only ever carried Namecheap's auto-provisioned defaults:
# a parking-page apex A + www CNAME, plus free email-forwarding MX
# (eforward1-5.registrar-servers.com) and the boilerplate efwd SPF TXT.
# There is no evidence the mail was ever used — no _dmarc, no DKIM
# selectors, no mail-client subdomains, only the default SPF — and the
# parking page just served Namecheap ads. So on the move to Cloudflare we
# dropped everything: no website (better absent than showing ads) and no
# mail (never used).
#
# The zone stays registered + delegated to Cloudflare (see local.zones)
# but holds no records by design. If Eve ever needs email here, Cloudflare
# Email Routing is the native replacement for the old Namecheap forwarder.
