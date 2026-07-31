#!/bin/sh
set -eu

API=http://forgejo:3000/api/v1
CONFIG=/provision/users.json
KEY_ROOT=/provision/keys

admin_username=${FORGEJO_ADMIN_USERNAME:?set FORGEJO_ADMIN_USERNAME}
admin_password=${FORGEJO_ADMIN_PASSWORD:?set FORGEJO_ADMIN_PASSWORD}
managed_prefix=$(jq -er '.managed_key_prefix' "$CONFIG")

api() {
  curl -fsS --user "$admin_username:$admin_password" \
    -H 'Content-Type: application/json' "$@"
}

wait_for_forgejo() {
  attempt=0
  until api "$API/version" >/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
      echo "Forgejo API did not become ready" >&2
      return 1
    fi
    sleep 2
  done
}

ensure_user() {
  user=$1
  username=$(printf '%s' "$user" | jq -er '.username')
  email_env=$(printf '%s' "$user" | jq -er '.email_env')
  password_env=$(printf '%s' "$user" | jq -er '.password_env')
  admin=$(printf '%s' "$user" | jq -r '.admin')
  email=$(printenv "$email_env")
  password=$(printenv "$password_env")

  status=$(curl -sS --user "$admin_username:$admin_password" \
    -o /dev/null -w '%{http_code}' "$API/users/$username")
  case "$status" in
    200) ;;
    404)
      body=$(jq -n \
        --arg username "$username" \
        --arg email "$email" \
        --arg password "$password" \
        '{username:$username,email:$email,password:$password,must_change_password:false}')
      api -X POST -d "$body" "$API/admin/users" >/dev/null
      ;;
    *)
      echo "Unexpected status checking Forgejo user $username: $status" >&2
      return 1
      ;;
  esac

  body=$(jq -n \
    --arg email "$email" \
    --arg password "$password" \
    --argjson admin "$admin" \
    '{
      email:$email,
      password:$password,
      admin:$admin,
      active:true,
      restricted:false,
      prohibit_login:false,
      must_change_password:false
    }')
  api -X PATCH -d "$body" "$API/admin/users/$username" >/dev/null
  printf '%s\n' "$username"
}

reconcile_keys() {
  user=$1
  username=$(printf '%s' "$user" | jq -er '.username')
  keys_directory=$(printf '%s' "$user" | jq -er '.keys_directory')
  desired=$(mktemp)
  current=$(mktemp)

  for key_file in "$KEY_ROOT/$keys_directory"/*.pub; do
    test -f "$key_file"
    title="${managed_prefix}$(basename "$key_file" .pub)"
    key=$(awk '{print $1 " " $2}' "$key_file")
    jq -cn --arg title "$title" --arg key "$key" '{title:$title,key:$key}'
  done | jq -s '.' > "$desired"

  api "$API/users/$username/keys" > "$current"

  jq -c --arg prefix "$managed_prefix" '.[] | select(.title | startswith($prefix))' "$current" |
    while IFS= read -r existing; do
      id=$(printf '%s' "$existing" | jq -er '.id')
      title=$(printf '%s' "$existing" | jq -er '.title')
      key=$(printf '%s' "$existing" | jq -er '.key | split(" ")[0:2] | join(" ")')
      if ! jq -e --arg title "$title" --arg key "$key" \
        '.[] | select(.title == $title and .key == $key)' "$desired" >/dev/null; then
        api -X DELETE "$API/admin/users/$username/keys/$id" >/dev/null
      fi
    done

  api "$API/users/$username/keys" > "$current"
  jq -c '.[]' "$desired" |
    while IFS= read -r wanted; do
      title=$(printf '%s' "$wanted" | jq -er '.title')
      key=$(printf '%s' "$wanted" | jq -er '.key')
      if ! jq -e --arg title "$title" --arg key "$key" \
        '.[] | select(.title == $title and (.key | split(" ")[0:2] | join(" ")) == $key)' \
        "$current" >/dev/null; then
        api -X POST -d "$wanted" "$API/admin/users/$username/keys" >/dev/null
      fi
    done

  final=$(api "$API/users/$username/keys")
  actual_managed=$(printf '%s' "$final" | jq -c --arg prefix "$managed_prefix" \
    '[.[] | select(.title | startswith($prefix)) | {
      title,
      key:(.key | split(" ")[0:2] | join(" "))
    }] | sort_by(.title)')
  desired_managed=$(jq -c 'sort_by(.title)' "$desired")
  test "$actual_managed" = "$desired_managed"

  rm -f "$desired" "$current"
  echo "reconciled $username: $(printf '%s' "$desired_managed" | jq 'length') managed SSH key(s)"
}

wait_for_forgejo
jq -c '.users[]' "$CONFIG" |
  while IFS= read -r user; do
    ensure_user "$user" >/dev/null
    reconcile_keys "$user"
  done
