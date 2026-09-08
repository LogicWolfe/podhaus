# Doggos Alive (doggos.indigo.pod.haus)

Indigo's website about dogs (and snakes), built in **Blocs for iPad**. The
site is a static export served from the `doggos-indigo` MinIO bucket on
bilby; Indigo publishes new versions into that bucket herself from Blocs.

## How it is served

Numbat relay → rathole → Caddy `:4444` (`caddy/Caddyfile`, the
`doggos_site` snippet) → `minio:9000`, bucket `doggos-indigo`. Pretty URLs
map to bucket keys (`/` → `index.html`, `/x/` and `/x` → `x/index.html`,
everything else verbatim); a missing key is a real 404 with the site's own
`404.html`. `Cache-Control: no-cache`, so browsers revalidate on ETag; Blocs
already busts its CSS and JS with query strings. No CDN — pod.haus is not a
cache zone.

The bucket allows anonymous `GetObject` only. Nobody can list it. Versioning
is on, so every publish keeps the file it replaced.

Terraform owns the bucket, its policies, the deploy user, and both
1Password items (`terraform/minio.tf`). Gatus checks the public URL.
`/var/lib/minio` is under the `minio` Backrest plan.

## How Indigo publishes

MinIO runs an SFTP server (`--sftp` in `minio/compose.yaml`) on
`bilby.pod.haus:8022`, reachable **from the home network only** (a
Docker-published port; bilby has no path from outside except the relay).
Its host key is Terraform-generated and held in 1Password
(**MinIO SFTP Host Key**), written into the container by `minio-secrets-init`
at every deploy, so it never changes and her iPad never sees a changed-key
warning.

She logs in as the MinIO user `doggos-indigo-deploy`, whose policy reaches
only her bucket. Everything for Blocs' *Publish* screen is in the 1Password
Homelab item **Doggos Indigo Publish**:

| Blocs field | Value |
|---|---|
| Address | `bilby.pod.haus` |
| Port | `8022` |
| Protocol | SFTP |
| Username | `doggos-indigo-deploy` |
| Password | the item's password |
| Path | `/doggos-indigo` |

First publish: *entire site*. After that: *just the changes*.

Known SFTP limits of MinIO: no rename, no append. Uploads, folders,
overwrites and deletes all work (a folder shows up as an empty `name/`
marker object, which is harmless).

**If Blocs' own publisher will not talk to MinIO**, she exports the site to
the Files app and uploads the folder with an SFTP app (FTP Files, Documents
by Readdle) using the same settings. Failing that, someone with the export
runs `mcli mirror --overwrite <export>/ doggos/doggos-indigo/` on bilby with
her credential.

## Rolling back a bad publish

On bilby, with her credential from 1Password:

```
mcli alias set doggos http://127.0.0.1:9000 doggos-indigo-deploy '<password>'
mcli ls --versions doggos/doggos-indigo/index.html      # see what there is
mcli undo doggos/doggos-indigo/index.html               # put back the previous version
mcli undo --action put --last 5 doggos/doggos-indigo/   # undo the last five uploads in the bucket
mcli alias remove doggos
```

## Rotating her password

Set `update_secret = true` on `minio_iam_user.doggos_indigo_deploy` in
`terraform/minio.tf`, apply, set it back. The 1Password item follows
because Terraform writes it. Then re-enter the password in Blocs.

## The editable original

The bucket and the site hold Blocs' *export*. The editable project file is
on Indigo's iPad and nowhere else; it should be in that iPad's iCloud
backup. Without it the site stays up but cannot be changed except by
editing the exported HTML.
