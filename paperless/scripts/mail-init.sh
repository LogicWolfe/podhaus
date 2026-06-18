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

# 2. Tag email-ingest (name filter is reliable across the ~120-tag corpus).
TAG_ID=$(auth_get "/tags/?name__iexact=email-ingest" | jq -r '.results[0].id // empty')
if [ -z "$TAG_ID" ]; then
  TAG_ID=$(auth_send POST "/tags/" "$(jq -n '{name:"email-ingest"}')" | jq -r '.id')
fi

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

# 4. Mail rule. Full-email-for-everything:
#    consumption_scope 2 = process full mail as one .eml document
#    attachment_type   2 = include inline attachments (note use case's image)
#    pdf_layout        2 = HTML then text (toweosp: use HTML if present)
#    action            1 = DELETE source mail (only after a successful parse)
#    assign_title_from 1 = use subject as document title
RULE=$(jq -n \
  --argjson acct "$ACCT_ID" \
  --argjson tag "$TAG_ID" \
  '{name:"Paperless ingest", account:$acct, enabled:true, folder:"Paperless",
    order:0, consumption_scope:2, attachment_type:2, pdf_layout:2,
    action:1, assign_title_from:1, assign_tags:[$tag]}')
RULE_ID=$(auth_get "/mail_rules/" | jq -r '.results[] | select(.name=="Paperless ingest") | .id' | head -n1)
if [ -z "$RULE_ID" ]; then
  auth_send POST "/mail_rules/" "$RULE" > /dev/null
else
  auth_send PATCH "/mail_rules/$RULE_ID/" "$RULE" > /dev/null
fi

echo "[mail-init] ok: tag=$TAG_ID account=$ACCT_ID rule=${RULE_ID:-new}"
