#!/usr/bin/env python3
# Moves finished StreamFab downloads out of /data/Downloads (nested by
# streaming service) into the Plex library, file by file.
#
# Why this exists: StreamFab writes captures into /data/Downloads/<Service>/
# <Show>/<Season>/<file>.mp4 (TV) or /data/Downloads/<Service>/<Title>/
# <file>.mp4 (movies). Plex doesn't see that tree, so finished media has to
# be relocated into the library. StreamFab is used only for kids' content
# here, so everything lands under Kids: /data/Kids/TV or /data/Kids/Movies.
# A plain move is correct — no seeding obligation like torrents — and leaves
# no second copy on disk.
#
# Completion signal: StreamFab muxes in a scratch dir, writes the final mp4
# under a numeric staging name (e.g. 33653334.mp4) in the Downloads tree,
# then atomically renames it to its real <Show>_SxxExx_<Title>.mp4 name. So
# any non-numeric .mp4 we see is, by construction, already complete — no
# quiescence wait needed; we only have to skip the numeric staging name.
# (This holds while StreamFab's temp dir is on the same filesystem as the
# output dir, so the staging rename is atomic. If temp is on a different
# filesystem the final file instead arrives as a growing copy and a
# size-stable guard would be needed — verify with the monitor after any
# temp-dir change.)
#
# Driven by an ofelia tick every minute (single-flight via flock). Runs as
# uid 1000 so moved files and any created library dirs are owned like the
# rest of the download/library tree. Logs to stdout — ofelia captures it.

import fcntl
import os
import re
import sys
import time
import urllib.request

DOWNLOAD_ROOT = "/data/Downloads"
# StreamFab is kids-only here, so both destinations live under Kids.
TV_ROOT = "/data/Kids/TV"
MOVIE_ROOT = "/data/Kids/Movies"
SENTINEL = "/data/.podhaus-share-mounted"
LOCK_FILE = "/tmp/streamfab-publish.lock"
GATUS_ENDPOINT = (
    "http://gatus:8080/api/v1/endpoints/"
    "plex_streamfab-publish/external?success=true"
)

# Directory names anywhere under Downloads that are StreamFab scratch or a
# separate domain (YouTube), never Plex TV/Movie output. The scratch dirs
# follow StreamFab's temp-dir setting; YouTube is deliberately out of scope.
SKIP_DIRS = {"outputTemp", "mpd", "picture", "MetaPicture", "YouTube"}

VIDEO_EXTS = {".mp4", ".mkv", ".m4v"}
SXXEXX = re.compile(r"[Ss]\d{1,2}[Ee]\d{1,3}")
NUMERIC_STEM = re.compile(r"^\d+$")  # StreamFab's transient staging name


def log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S %Z"), msg), flush=True)


def classify(parts):
    """Map a Downloads-relative path to (library_root, dest_relative_path).

    `parts` is the path split on '/', e.g.
    ['Netflix', 'Sealook', 'S01', 'Sealook_S01E01_Trick Shot.mp4'].
    The leading service component is dropped; the rest is preserved verbatim
    under Kids/TV or Kids/Movies. Returns None for anything that doesn't fit the
    expected <Service>/<Show-or-Title>/.../<file> shape — left in place,
    never guessed at.
    """
    if len(parts) < 3:  # need at least Service / Title / file
        return None
    root = TV_ROOT if SXXEXX.search(parts[-1]) else MOVIE_ROOT
    return root, os.path.join(*parts[1:])


def is_candidate(rel):
    parts = rel.split(os.sep)
    if any(p in SKIP_DIRS for p in parts):
        return False
    name = parts[-1]
    if name.startswith("._"):  # macOS AppleDouble sidecar
        return False
    stem, ext = os.path.splitext(name)
    if ext.lower() not in VIDEO_EXTS:
        return False
    if NUMERIC_STEM.match(stem):  # transient staging file, mid-rename
        return False
    return True


def prune_empty(start_dir):
    """Best-effort rmdir up the chain after a move, stopping at the first
    non-empty dir or at Downloads itself. rmdir only succeeds when empty, so
    a show dir still holding other episodes is left untouched."""
    d = start_dir
    while d.startswith(DOWNLOAD_ROOT + os.sep):
        try:
            os.rmdir(d)
        except OSError:
            return
        d = os.path.dirname(d)


def publish(src):
    rel = os.path.relpath(src, DOWNLOAD_ROOT)
    mapped = classify(rel.split(os.sep))
    if mapped is None:
        log("SKIP unrecognized layout: %s" % rel)
        return
    root, dest_rel = mapped
    dest = os.path.join(root, dest_rel)
    if os.path.exists(dest):
        # Same size => StreamFab re-downloaded an episode already in the
        # library; drop the duplicate source. Different size => a different
        # cut; leave both and let a human decide rather than clobber.
        if os.path.getsize(dest) == os.path.getsize(src):
            os.remove(src)
            log("DUP already in library, removed source: %s" % rel)
        else:
            log("CONFLICT %s exists with different size, leaving source" % dest)
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(src, dest)  # same NFS filesystem -> atomic, instant
    log("moved %s -> %s" % (rel, dest))
    prune_empty(os.path.dirname(src))


def heartbeat():
    req = urllib.request.Request(
        GATUS_ENDPOINT,
        data=b"",
        method="POST",
        headers={
            "Authorization": "Bearer " + os.environ["GATUS_OFELIA_PUSH_TOKEN"]
        },
    )
    urllib.request.urlopen(req, timeout=10).read()


def main():
    if not os.path.exists(SENTINEL):
        # Pouch isn't mounted: /data is a bare local-disk stub and moving
        # would scatter media onto bilby's NVMe. Refuse loudly.
        log("ABORT: %s missing — Pouch NFS not mounted, not moving anything"
            % SENTINEL)
        sys.exit(1)

    lock = None
    try:
        lock = open(LOCK_FILE, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # a prior tick is still running; it sees the same state
    except OSError as exc:
        log("WARN: single-flight lock unavailable (%s); continuing" % exc)

    for dirpath, dirnames, filenames in os.walk(DOWNLOAD_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            src = os.path.join(dirpath, name)
            if not is_candidate(os.path.relpath(src, DOWNLOAD_ROOT)):
                continue
            try:
                publish(src)
            except Exception as exc:  # one bad file must not abort the pass
                log("ERROR moving %s: %s" % (src, exc))


if __name__ == "__main__":
    try:
        main()
        heartbeat()
    except Exception as exc:
        log("FATAL: %s" % exc)
        sys.exit(1)
