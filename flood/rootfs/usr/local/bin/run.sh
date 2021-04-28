#!/bin/sh

rm -f /data/.session/rtorrent.lock

chown -R $UID:$GID /etc/s6.d /usr/flood

exec su-exec $UID:$GID /bin/s6-svscan /etc/s6.d