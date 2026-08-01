# Adds libarchive-tools to the upstream jesec/rtorrent-flood image so the
# event.download.finished hook (scripts/rtorrent-extract.sh) can extract
# multi-volume RARs in place. This is the local replacement for the
# previous unpackerr stack — rtorrent already knows the exact path each
# torrent landed under, so a finish-hook + extract step gives us
# arbitrary-depth extraction with no recursive filesystem watcher and no
# enumeration of nested subdirs to maintain.
#
# Why bsdtar (libarchive) not 7zip:
#   - Alpine 3.x's `p7zip` package now resolves to `7zip-25.x`, a slim
#     build that does NOT ship the RAR codec.
#   - Alpine no longer ships a standalone `unrar` package (license).
#   - libarchive's `bsdtar` includes RAR read support (RAR4 + RAR5,
#     multi-volume) and is permissively licensed. Multi-volume
#     sequencing works when all volumes are in the same directory —
#     point bsdtar at the main `.rar` and it walks `.r00`, `.r01`, …
#     automatically.
#   - bsdtar exits non-zero with "Truncated RAR file data" at the last
#     volume boundary even on full successful extractions; the script
#     verifies by counting new non-archive files in the target dir
#     rather than trusting the exit code.
FROM jesec/rtorrent-flood:latest

# libarchive-tools → bsdtar for the RAR extract hook.
# python3 → flood-publish.py, which queries rtorrent over the SCGI socket
#   for per-file completion and hardlinks completed media into the library
#   (see flood/scripts/flood-publish.py + docs/runbooks/flood.html).
# plexapi (via pip) → plex-label-sync.py, which mirrors Flood tags onto the
#   matching Plex show/movie as Labels. --break-system-packages: Alpine's
#   python3 is PEP-668 externally-managed and there's no py3-plexapi apk.
USER root
RUN apk add --no-cache libarchive-tools python3 py3-pip \
    && pip install --no-cache-dir --break-system-packages plexapi

# Content-hash build arg from the podhaus mechanism (see AGENTS.md
# "Content-hash change detection"). Declared here purely for cache
# busting: setting it as an ENV from the ARG means a different
# STACK_CONTENT_HASH value produces a different layer hash, so any
# change to a tracked file in this stack's build context invalidates
# everything from this layer down and forces a real rebuild. The value
# is never read by the running container — its sole purpose is layer
# fingerprinting.
ARG STACK_CONTENT_HASH=unset
ENV STACK_CONTENT_HASH=${STACK_CONTENT_HASH}

USER 1000
