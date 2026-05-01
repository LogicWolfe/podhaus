# garethgeorge/backrest:latest is alpine-based but doesn't ship envsubst.
# We use envsubst in the entrypoint to render config.json from the
# template + RESTIC_REPO_PASSWORD env var. Bake gettext (which provides
# envsubst) into the image once instead of `apk add` on every boot.
#
# Built locally by docker compose via the `build:` directive in the
# kangaroo-backrest stack's compose.yaml; image is tagged
# kangaroo-backrest:local and pull_policy: never tells compose to use
# the locally-built image rather than trying to pull from a registry.
FROM garethgeorge/backrest:latest

RUN apk add --no-cache gettext
