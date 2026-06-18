# Custom Paperless-ngx image: stock image + toweosp/paperlessngx-mail-parser.
#
# The parser subclasses the upstream MailDocumentParser, registers for
# message/rfc822 (.eml) at weight 30 (beats the stock parser), and renders
# each email as one document — body + attachments bundled, a copy-pasteable
# text version prepended, PDF/A out. It still uses the existing Gotenberg +
# Tika sidecars for the HTML→PDF step. This is what powers "full-email mode
# for everything" (see docs/plans/.../paperless-email-ingest.md).
#
# Installed into the image's system Python: the upstream image installs its
# own deps with `uv pip install --system` (no venv), and runs as root, so
# matching that mechanism lands the package where Paperless imports from.
# Pinned deliberately — toweosp couples to Paperless internals; bump in
# lockstep with Paperless upgrades, or delete this RUN to fall back to the
# stock Gotenberg-rendered mail parser.
FROM ghcr.io/paperless-ngx/paperless-ngx:latest

RUN uv pip install --no-cache --system paperlessngx-mail-parser==2.0.2

# Content-hash build arg (see AGENTS.md "Content-hash change detection").
# Busts the build-layer cache when paperless/'s content hash changes.
ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}
