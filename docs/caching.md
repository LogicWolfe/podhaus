# Public site caching

Cloudflare caches only the three public sites that opt into this contract:
`nathanbaxter.com`, `pets.indigopod.au`, and `skycroeser.net`. Protected
services stay outside the CDN.

## Contract

Terraform makes `GET` and `HEAD` responses for each site eligible for caching,
uses `bypass_by_default`, respects the browser policy from the origin, and
enables Tiered Caching with Smart topology. The origin remains authoritative for
each response:

| Response | `Cache-Control` | `CDN-Cache-Control` | `Cache-Tag` |
|---|---|---|---|
| Mutable release content | `no-cache` | `public, max-age=31536000` | Stable site tag |
| Content-addressed asset | `public, max-age=31536000, immutable` | `public, max-age=31536000` | None |
| Dynamic or private content | `no-store` | None | None |

Mutable content therefore revalidates in the browser but may remain at the edge
for a year. A completed deployment purges the stable site tag. Immutable assets
do not need a purge because their URL changes with their content.

`terraform/cache.tf` owns only hostname eligibility and tiered caching. Route
classes and cache tags stay with the site stack.

## Sites

| Site | Origin policy | Invalidation boundary |
|---|---|---|
| `nathanbaxter.com` | Caddy treats `/_astro/*` as immutable and tags all other apex content `nathanbaxter`. | `nathanbaxter-deploy/build.sh` purges after the MinIO mirror completes. |
| `pets.indigopod.au` | Pets treats `/dist/*` and generated `/api/assets/*` objects as immutable, `/` and `/defaults/*` as release content tagged `pets`, and `/studio` plus every other `/api/*` response as `no-store`. | The Pets stack exposes its zone and tag through `podhaus.cloudflare-cache-*` labels. `podhaus-purge-stack-cache` discovers those labels and purges after deployment. |
| `skycroeser.net` | Caddy tags all apex content `skycroeser`. Publii output is not assumed to be content-addressed. | An Ofelia job checks MinIO's version ID for `files.publii.json` every minute. A new version means Publii finished its upload and deletion pass, so the job purges and then records that version. |

All three paths use the existing Cloudflare API token from 1Password. A missing
zone or tag, an ambiguous zone lookup, or a rejected purge is an error. Nathan's
builder and the Pets procedure fail. Sky keeps the prior manifest version so
Ofelia retries the same release on its next run.

## Adding a site

1. Add its hostname and zone to `terraform/cache.tf`.
2. Make the origin emit one of the three exact response contracts above.
3. Keep the stable tag and invalidation boundary with the stack that publishes
   the site.
4. Purge only after the release is complete. Do not add a timer when the deploy
   path already has that boundary.
5. Run `terraform plan`, deploy the origin change, then apply Terraform.

## Verification

Inspect each response class with `curl -I`. Mutable content must show the browser
and CDN policies above; immutable content must have no tag; dynamic content must
have no CDN policy. Cloudflare consumes `Cache-Tag`, so inspect it on the direct
origin path when it is absent from the proxied response.

After a cache rule is applied, request a release URL twice. The first response
should be `CF-Cache-Status: MISS` and the second should be `HIT` with an `Age`.
Run the site's deployment path and confirm the next response is a miss with the
new content, followed by a hit.
