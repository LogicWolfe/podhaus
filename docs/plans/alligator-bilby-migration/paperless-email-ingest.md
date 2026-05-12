# Paperless email ingest

Set up IMAP-based email ingestion so anything forwarded to a dedicated
alias lands in Paperless automatically. The compose env var
`PAPERLESS_EMAIL_TASK_CRON: "*/10 * * * *"` is already wired — the
scheduler runs every 10 minutes — but no email account has been
configured inside Paperless yet, so it's a no-op.

This is the last "complete the Paperless setup" item. Once done, the
ingest pipeline is: Fastmail alias → "Paperless Ingest" folder →
Paperless polls IMAP every 10 min → attachments extracted + tagged.

## Background

The original migration guide (commit `710c78d`, deleted when the
OneNote pipeline was rewritten) had a full Fastmail IMAP plan. Key
context preserved below:

- **Why Fastmail aliases over a user slot**: aliases are free up to
  600/account. `paperless@<domain>` is cleaner than burning a paid
  mailbox.
- **Why a dedicated folder**: a Fastmail mail rule files anything sent
  to the alias into a "Paperless Ingest" folder. Keeps archive-bound
  emails visible in the normal mailbox while giving Paperless a clean
  scope to monitor.
- **Why an app-specific password**: granting IMAP access with the main
  password is a much bigger blast radius. App passwords can be
  revoked individually under Fastmail → Privacy & Security → Manage
  app passwords without affecting other integrations or the main
  login.

## Setup steps

1. **Fastmail alias**: Settings → My email addresses → Add address →
   Create an alias → `paperless@<domain>`.
2. **Fastmail "Paperless Ingest" folder**: Settings → Folders →
   Create new.
3. **Fastmail mail rule**: file `to:paperless@<domain>` into the new
   folder. Optional: also catch `+paperless` plus-addressing if you
   want to use the main address with tagging.
4. **App password**: Settings → Privacy & Security → Manage app
   passwords → create one named "Paperless" with IMAP access. Store
   as a new 1P item `Paperless Fastmail IMAP`, fields `username`
   (the alias address) + `credential` (app password) +
   `hostname` (`imap.fastmail.com`) + `port` (`993`).
5. **`komodo-op` syncs the item** as
   `OP__KOMODO__PAPERLESS_FASTMAIL_IMAP__{USERNAME,CREDENTIAL,HOSTNAME,PORT}`
   variables — no compose change needed unless we want to expose them
   in the env (we don't; Paperless reads the email account from its
   own DB, not env).
6. **Paperless mail account** (admin UI → Settings → Mail):
   - IMAP server: `imap.fastmail.com`
   - Port: `993` (SSL)
   - Username: alias address
   - Password: app password from 1P
   - Test connection.
7. **Paperless mail rule**:
   - Account: the one just created.
   - Folder: `INBOX/Paperless Ingest` (or whatever the folder path
     resolves to — check via the test-connection folder dropdown).
   - Filters: by sender / subject / attachment as needed. Sensible
     default: process anything in the folder regardless of subject.
   - Action: extract attachments + body (email body to PDF via
     Gotenberg, already running in the stack).
   - Post-process: mark read + move to `INBOX/Paperless Ingest/Archived`
     so re-ingest doesn't duplicate.
   - Tags: auto-tag `email-ingest` for provenance.
8. **Smoke test**: send a PDF attachment to the alias from any other
   inbox, wait ≤10 min, confirm it appears in Paperless tagged
   `email-ingest`. Open Komodo's `paperless` logs to confirm no
   IMAP errors.

## Decisions to make at setup time

- **Email body → PDF or skip?** Default Paperless behaviour is to
  archive both attachments and the email body (rendered as PDF via
  Gotenberg). Skipping the body saves storage and noise if most
  ingest is "forward me a receipt" style where the body is just a
  greeting.
- **Auto-tag vs manual triage?** Mail rules can apply tags from the
  rule itself (e.g. `tags=[receipt, email-ingest]`) for known
  high-confidence senders. Open question whether to set up
  per-sender rules now or just one catch-all rule and let
  Paperless's ML classifier learn.
- **`emails-html-to-pdf` sidecar?** Community tool that produces
  cleaner email-to-PDF output than Gotenberg's default render of raw
  HTML email. Worth evaluating only if the default render quality
  turns out to be poor.

## Security note

Even an app-password-scoped IMAP login can read and write the entire
Fastmail mailbox, not just the monitored folder. Risk is bounded by:

- The token only exists in 1P (no plaintext on disk).
- The app password can be revoked instantly under Fastmail settings.
- The Paperless container only egresses to `imap.fastmail.com:993`;
  it can't exfiltrate other folders' contents off-network in any way
  that matters.

If the risk feels uncomfortable, the alternative is a hand-rolled
poller that uses a more narrowly-scoped Fastmail JMAP token and
deposits attachments into Paperless's `/usr/src/paperless/consume`
mount via the existing consume-folder watcher.

## Status

Not started. Estimated effort: ~30 min once the alias + folder + app
password exist.
