#!/bin/sh
# Idempotently provision the Paperless mail account + rule for Fastmail
# email ingest, from the Komodo-injected Fastmail IMAP credentials. Runs
# once per deploy (paperless-mail-init); safe to re-run — every object is
# looked up by name and PATCHed if present, POSTed if absent.
#
# This is the config-as-code path: mail accounts/rules are Paperless DB
# objects with no env/file config, so a DB wipe + redeploy re-creates them
# from 1Password with no manual UI step.
set -eu

API="http://paperless:8000/api"
# PAPERLESS_ALLOWED_HOSTS pins the Host header; over dockernet we hit the
# container name but must present the public host (see paperless runbook).
HOST="paperless.pod.haus"

auth_get() {
  curl -fsS "$API$1" -H "Host: $HOST" -H "Authorization: Token $TOKEN"
}
auth_send() {
  # method path json
  curl -fsS -X "$1" "$API$2" -H "Host: $HOST" \
    -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" -d "$3"
}

# 1. API token from the admin user. Retry: depends_on waits for the
#    healthcheck, but give the API a few seconds of slack regardless.
echo "[mail-init] obtaining API token..."
TOKEN=""
i=0
while [ "$i" -lt 30 ]; do
  TOKEN=$(curl -fsS -X POST "$API/token/" -H "Host: $HOST" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg u "$PAPERLESS_ADMIN_USER" --arg p "$PAPERLESS_ADMIN_PASSWORD" \
          '{username:$u,password:$p}')" 2>/dev/null \
    | jq -r '.token // empty') || true
  [ -n "$TOKEN" ] && break
  i=$((i + 1))
  sleep 2
done
[ -n "$TOKEN" ] || { echo "[mail-init] ERROR: no API token after retries" >&2; exit 1; }

# 2. Tags (name filter is reliable across the ~120-tag corpus). One per mail
#    pathway so ingested docs are filterable by which rule produced them.
ensure_tag() {
  id=$(auth_get "/tags/?name__iexact=$1" | jq -r '.results[0].id // empty')
  [ -n "$id" ] || id=$(auth_send POST "/tags/" "$(jq -n --arg n "$1" '{name:$n}')" | jq -r '.id')
  printf '%s' "$id"
}
TAG_ID=$(ensure_tag email-ingest)
TAG_ATTACH_ID=$(ensure_tag email-attachments)

# 3. Mail account Fastmail. imap_security 2=SSL, account_type 1=IMAP.
# Strip the injected port to digits so a stray newline can't break --argjson.
PORT=$(printf '%s' "$PAPERLESS_FASTMAIL_PORT" | tr -cd '0-9')
[ -n "$PORT" ] || { echo "[mail-init] ERROR: empty/invalid IMAP port" >&2; exit 1; }
ACCT=$(jq -n \
  --arg srv "$PAPERLESS_FASTMAIL_HOSTNAME" \
  --argjson port "$PORT" \
  --arg user "$PAPERLESS_FASTMAIL_USERNAME" \
  --arg pass "$PAPERLESS_FASTMAIL_PASSWORD" \
  '{name:"Fastmail", imap_server:$srv, imap_port:$port, imap_security:2,
    username:$user, password:$pass, is_token:false, account_type:1}')
ACCT_ID=$(auth_get "/mail_accounts/" | jq -r '.results[] | select(.name=="Fastmail") | .id' | head -n1)
if [ -z "$ACCT_ID" ]; then
  ACCT_ID=$(auth_send POST "/mail_accounts/" "$ACCT" | jq -r '.id')
else
  auth_send PATCH "/mail_accounts/$ACCT_ID/" "$ACCT" > /dev/null
fi

# 4. Mail rules. Two pathways on the same Paperless folder, split by recipient
#    address (filter_to) so each mail matches exactly one — no order/action
#    coupling needed for mutual exclusion (the substrings don't overlap:
#    "paperless@pod.haus" is not contained in "paperless+attachments@pod.haus").
#    Fastmail plus-addressing delivers both to the same mailbox; a Fastmail
#    rule must file both into the Paperless folder for these to see them.
#    Common to both: account, enabled, folder Paperless, action 1 = DELETE
#    source mail (only after a successful parse), assign a pathway tag.
upsert_rule() {
  # name json
  rid=$(auth_get "/mail_rules/" | jq -r --arg n "$1" '.results[] | select(.name==$n) | .id' | head -n1)
  if [ -z "$rid" ]; then
    auth_send POST "/mail_rules/" "$2" > /dev/null
  else
    auth_send PATCH "/mail_rules/$rid/" "$2" > /dev/null
  fi
}

# Full-email render (paperless@pod.haus):
#   consumption_scope 2 = full mail as one .eml document
#   attachment_type   2 = include inline attachments (note use case's image)
#   pdf_layout        2 = HTML then text (toweosp: use HTML if present)
#   assign_title_from 1 = subject as title
#   filter_to pins it to the bare address so it no longer also swallows
#   the +attachments variant.
upsert_rule "Paperless ingest" "$(jq -n \
  --argjson acct "$ACCT_ID" --argjson tag "$TAG_ID" \
  '{name:"Paperless ingest", account:$acct, enabled:true, folder:"Paperless",
    order:0, filter_to:"paperless@pod.haus", consumption_scope:2,
    attachment_type:2, pdf_layout:2, action:1, assign_title_from:1,
    assign_tags:[$tag]}')"

# Attachments only (paperless+attach…@pod.haus):
#   consumption_scope 1 = just the attached files, email body discarded
#   attachment_type   1 = real attachments only (skip inline signature images)
#   assign_title_from 2 = title from the attachment filename
#   filter_to is the bare "paperless+attach" substring (no suffix, no domain)
#   so the IMAP TO match catches attach / attachment / attachments and most
#   accidental spellings of the alias. Still disjoint from the bare-address
#   rule ("paperless@pod.haus" shares no substring with "paperless+attach…").
upsert_rule "Paperless attachments" "$(jq -n \
  --argjson acct "$ACCT_ID" --argjson tag "$TAG_ATTACH_ID" \
  '{name:"Paperless attachments", account:$acct, enabled:true, folder:"Paperless",
    order:1, filter_to:"paperless+attach", consumption_scope:1,
    attachment_type:1, action:1, assign_title_from:2, assign_tags:[$tag]}')"

echo "[mail-init] ok: account=$ACCT_ID tags=$TAG_ID,$TAG_ATTACH_ID rules=ingest+attachments"
