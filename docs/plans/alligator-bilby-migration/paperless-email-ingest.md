# Paperless email ingest

Set up IMAP-based email ingestion so anything sent or forwarded to a
dedicated alias lands in Paperless automatically as one searchable,
provenance-stamped document. The compose env var
`PAPERLESS_EMAIL_TASK_CRON: "*/10 * * * *"` is already wired — the
scheduler runs every 10 minutes — but no email account is configured
inside Paperless yet, so it's a no-op.

## Settled design — full-email mode for everything

One alias, one folder, one Paperless mail rule, **one consumption
mode**: every email becomes a single document containing the rendered
body *plus* its attachments, with full email headers (From / To /
Subject / Date) for provenance.

Decisions made during planning, and why:

- **Full-email mode, not attachment-only.** Every email →
  one bundled document. Simpler than routing receipts vs notes vs
  forwards through different modes — no subject prefixes, no
  forward-button discipline, no plus-addressing. The cost is cosmetic
  (a header + body page in front of forwarded attachments) plus one
  functional trade: the document's stored original is the email
  render, not the pristine standalone attachment. Accepted because the
  dominant use is "archive it so I can find it later." It's a config
  choice, reversible by adding an attachment-only rule later if the
  bundling ever bites.
- **This also delivers the "create a note" use case.** Compose an
  email with an inline image (e.g. a driver's licence) and typed text
  below → one document where the typed text is a real, copy-pasteable
  text layer, the image is OCR'd, everything searchable. No separate
  routing needed — it's the same mode as everything else.
- **toweosp/paperlessngx-mail-parser**, not the upstream default
  parser and not the WeasyPrint engine-swap. It's a maintained PyPI
  package (v2.0.2, Mar 2026, 12 releases) that subclasses the upstream
  `MailDocumentParser` and improves email *handling*: embeds
  attachments into one document, prepends a plain-text version of the
  body (copy-paste + search), preserves headers, emits PDF/A. It still
  renders HTML→PDF via the existing Gotenberg + Tika sidecars (it
  reuses the `gotenberg_client`/`tika_client` libs Paperless already
  bundles), so those stay.
- **Render-engine quality deferred.** camerono/paperless-weasyprint is
  the only thing that swaps Chromium for WeasyPrint, but it's an
  unmaintained 2-commit stopgap. Not worth the risk until we actually
  see Gotenberg produce an ugly render. Revisit then.

## Part 1 — Fastmail setup (manual)

Do these in the Fastmail web UI. The alias is **receive-only** — it's
where you send/forward documents; it is *not* the IMAP login.

1. **Alias** — Settings → My email addresses → add `paperless@<your
   Fastmail domain>` (e.g. `paperless@nathanbaxter.com`). Delivers to
   your normal account.
2. **Folder** — Settings → Folders → create `Paperless`. Processed
   mail is deleted from it (see the Paperless rule below), so no
   archive subfolder is needed.
3. **Mail rule** — Settings → Rules → if recipient contains
   `paperless@<domain>`, file into `Paperless`. Keep it visible
   in your normal mail too if you like; Paperless only needs the
   folder copy.
4. **App password** — Settings → Privacy & Security → App passwords →
   new, named `Paperless`, scope **Mail (IMAP)**. Copy the generated
   password once — it's shown only at creation. Revocable here anytime
   without touching your main login.

## Part 2 — Where to put the results (1Password)

Create one item in the **Homelab** vault named **`Paperless Fastmail
IMAP`** with these fields:

| Field | Value |
|---|---|
| `username` | Your **primary** Fastmail login email (e.g. `nathan@nathanbaxter.com`) — **not** the alias. Fastmail IMAP authenticates as the account, not the alias. |
| `password` | The app password from step 4. |
| `hostname` | `imap.fastmail.com` |
| `port` | `993` |

Put the alias address (`paperless@<domain>`) in the item's notes for
reference — it's config, not a credential.

`komodo-op` syncs the item as
`OP__KOMODO__PAPERLESS_FASTMAIL_IMAP__{USERNAME,PASSWORD,HOSTNAME,PORT}`
Komodo Variables. These **are** consumed: the stack's `stack.toml`
references them as `[[…]]` env entries, injected into the
`paperless-mail-init` container (Part 3), which upserts the mail
account + rule into Paperless via the REST API on every deploy. So the
config is reproducible from 1P — a Paperless DB wipe + redeploy
re-creates the account and rule with no manual UI step. The app
password stays a Komodo-variable *reference* end to end; it never
appears in plaintext in the repo or the agent's context.

## Part 3 — Parser install (code; done by agent)

toweosp is a Python package with no separate container — it installs
into the Paperless image and auto-registers as the `.eml`
(`message/rfc822`) parser. This means flipping the `paperless` service
from a pinned `image:` to a `build:`, following the same pattern as
`relay/bilby` (`build:` block + `image: <name>:local` +
`pull_policy: never`).

- **`paperless/Dockerfile`** (new):
  `FROM ghcr.io/paperless-ngx/paperless-ngx:latest` (matches the
  current pin), a `RUN` that installs `paperlessngx-mail-parser==2.0.2`,
  then the `ARG STACK_CONTENT_HASH=unset` / `ENV
  STACK_CONTENT_HASH=${STACK_CONTENT_HASH}` pair (matching
  `relay/Dockerfile`).
- **`paperless/compose.yaml`** — `paperless` service: replace
  `image: ghcr.io/...` with a `build: { context: ., dockerfile:
  Dockerfile, args: { STACK_CONTENT_HASH: ${BUILD_HASH_PAPERLESS:-unset}
  } }` block plus `image: paperless-ngx:local` + `pull_policy: never`.
  Add `PAPERLESS_APPS: paperlessngx_mail_parser.apps.MailparserConfig`
  to the environment. The `podhaus.stack-content-hash` label is
  already present. Keep `paperless-gotenberg` + `paperless-tika` (the
  parser uses both). No new `depends-on-<dep>` labels: `paperless` is
  the only build service and nothing depends on it.
- **`paperless/stack.toml`** — add `run_build = true` to
  `[stack.config]`.
- **Lint** — `tools/lint-stack-content-hash.py` enforces the
  build-arg + Dockerfile ARG wiring; the above satisfies it.

**Install-mechanism risk to verify before deploy.** The official
paperless-ngx image installs its Python into a managed venv, so a bare
`pip install` in a derived Dockerfile may not land in the environment
Paperless actually imports from — toweosp's own docs hint at a
runtime init-script install for exactly this reason. Confirm the
correct in-image install (right `pip`/venv path, or the documented
hook) against the current image before relying on it; a wrong install
fails silently — the parser just never registers and emails fall back
to the stock parser. Smoke test (Part 4) catches it.

Version-coupling caveat: toweosp pins to Paperless internals
(`paperless_mail.parsers`, the `gotenberg_client` API). The repo runs
Paperless at `:latest`, so a Paperless bump could outrun the parser.
The 12-release cadence tracking upstream is why this is tolerable;
if a Paperless upgrade breaks the parser, bump
`paperlessngx-mail-parser` or remove the one install line to fall
back to stock rendering.

### Programmatic mail config — `paperless-mail-init`

Paperless mail accounts + rules are DB objects with no env-var or
file config path, but they're fully manageable over the REST API. To
keep the config reproducible (rebuild without web-UI steps), a one-shot
init container upserts both on every deploy — the same shape as
`plex-preferences-init`.

- **Service** `paperless-mail-init` in `paperless/compose.yaml`:
  `build: { context: ../init-tools }` (the shared curl+jq image, as
  `tailscale-cleanup`/`backup` use) → `image: init-tools:local`,
  `build.args.STACK_CONTENT_HASH: ${BUILD_HASH_PAPERLESS_MAIL_INIT:-unset}`,
  the `podhaus.stack-content-hash` label, `depends_on: { paperless:
  { condition: service_healthy } }`, runs `paperless/scripts/mail-init.sh`
  (bind-mounted; stack-dir change → recreate via the content hash).
- **`paperless/stack.toml`** — add the IMAP env refs and
  `ignore_services = ["paperless-mail-init"]` (one-shot exits 0; without
  it Komodo marks the whole stack Unhealthy):
  ```
  PAPERLESS_FASTMAIL_USERNAME=[[OP__KOMODO__PAPERLESS_FASTMAIL_IMAP__USERNAME]]
  PAPERLESS_FASTMAIL_PASSWORD=[[OP__KOMODO__PAPERLESS_FASTMAIL_IMAP__PASSWORD]]
  PAPERLESS_FASTMAIL_HOSTNAME=[[OP__KOMODO__PAPERLESS_FASTMAIL_IMAP__HOSTNAME]]
  PAPERLESS_FASTMAIL_PORT=[[OP__KOMODO__PAPERLESS_FASTMAIL_IMAP__PORT]]
  ```
  (`lint-stack-env.py` requires each to be referenced in the init
  service's `environment`.)
- **`paperless/scripts/mail-init.sh`** — idempotent, against
  `http://paperless:8000` with an explicit `Host: paperless.pod.haus`
  header (the `PAPERLESS_ALLOWED_HOSTS` constraint; see runbook). Steps:
  1. Obtain an API token: `POST /api/token/` with the existing
     `PAPERLESS_ADMIN_USER`/`PASSWORD` env.
  2. Upsert tag `email-ingest`: `GET /api/tags/?name__iexact=…` →
     POST if absent.
  3. Upsert mail account `Fastmail`: `GET /api/mail_accounts/?name=…`
     → POST/PATCH `/api/mail_accounts/[<id>/]` with
     `imap_server`=hostname, `imap_port`=993, `imap_security`=2 (SSL),
     `username`, `password`, `is_token`=false, `account_type`=1 (IMAP).
  4. Upsert mail rule `Paperless ingest`: `GET /api/mail_rules/?name=…`
     → POST/PATCH `/api/mail_rules/[<id>/]` with `account`=<id>,
     `folder`=`Paperless` (confirm the exact IMAP folder path —
     Fastmail may expose it as `INBOX.Paperless`), no `filter_*`
     (process everything), `consumption_scope`=2 (EML_ONLY — full mail
     as one .eml doc, the full-email-for-everything mode),
     `attachment_type`=2 (include inline attachments — needed so the
     note use case's inline image is processed), `pdf_layout`=2
     (HTML, then text — toweosp reads this as "use HTML if present",
     so note bodies render the image while its text-header still
     gives copy-paste), `action`=1 (**DELETE** — Paperless removes the
     source mail, but only after a successful parse), `assign_tags`=
     [<email-ingest id>], `title_source`=1 (subject → document title).

The enum integers are from `paperless_mail/models.py` (MailAccount /
MailRule `IntegerChoices`). Confirm them against the deployed
`/api/schema/` at implement time — they're stable but worth a check.

## Part 4 — Deploy + smoke test

1. **Deploy** (needs explicit authorization): commit + push fires the
   webhook → builds the custom Paperless image + the init image,
   recreates the stack, and `paperless-mail-init` upserts the account
   + rule. Confirm via config-level signals — the rebuilt image, the
   parser registering in `paperless` logs, and the init container's
   exit-0 + "account/rule upserted" output — not just "container
   healthy".
2. **Smoke test**: forward a PDF, and separately send a note-style
   email (inline image + typed text) to `paperless@<domain>`. Within
   ≤10 min both appear tagged `email-ingest` — the forward as a
   bundled email+PDF doc, the note as one doc whose typed text is
   copy-pasteable. Check `paperless` logs for IMAP / parser errors,
   and confirm the source emails were deleted (moved to Fastmail
   Trash) after processing.

## Security note

An app-password-scoped IMAP login can read/write the whole Fastmail
mailbox, not just the monitored folder. Bounded by: the token lives
only in 1P (no plaintext on disk), it's revocable instantly in
Fastmail settings, and the Paperless container only egresses to
`imap.fastmail.com:993`.

## Status

**Deployed and live** (2026-06-18). Custom Paperless image (toweosp
parser, baked via `uv pip install --system`) + `paperless-mail-init`
are running; the parser wins `message/rfc822` dispatch and the
`Fastmail` account + `Paperless ingest` rule (full-email scope, delete
after parse, tag `email-ingest`) are configured in the DB. Awaiting the
final user smoke test: send/forward mail to `paperless@nathanbaxter.com`
and confirm it lands within ≤10 min.

Deploy gotcha encountered: a `stack.toml`-only change (surfacing
`PODHAUS_REPO`) didn't trigger Stage 2 IfChanged — the redeploy needed
a change to a hashed runtime file (`compose.yaml`). The current state
needs no further pushes.

Once the smoke test passes, fold any remaining current-state detail
into the runbook and delete this plan per the docs/plans contract.
