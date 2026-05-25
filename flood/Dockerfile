# Adds p7zip to the upstream jesec/rtorrent-flood image so the
# event.download.finished hook (scripts/rtorrent-extract.sh) can extract
# multi-volume RARs in place. This is the local replacement for the
# previous unpackerr stack — rtorrent already knows the exact path each
# torrent landed under, so a finish-hook + extract step gives us
# arbitrary-depth extraction with no recursive filesystem watcher and no
# enumeration of nested subdirs to maintain.
FROM jesec/rtorrent-flood:latest

USER root
RUN apk add --no-cache p7zip
USER 1000
