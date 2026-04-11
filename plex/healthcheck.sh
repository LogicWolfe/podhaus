#!/bin/sh
# Runs inside the plex container every 60s.
# Fails if Plex API is down or NFS mounts are unreadable.
set -e

curl -sf http://localhost:32400/identity > /dev/null

ls /Users/Shared/Pouch/Movies > /dev/null
ls /config/Library > /dev/null
