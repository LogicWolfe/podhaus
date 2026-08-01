#!/usr/bin/env python3
# Publishes completed media out of rtorrent's download tree
# (/data/torrents) into the Plex library as hardlinks, file by file.
#
# Why this exists: torrents download into /data/torrents (Plex-invisible),
# never into the library. This script links each completed media file into
# the publish target the user picked at add-time — so a prioritized episode
# appears in Plex the moment it lands, not when the whole season finishes,
# and Plex never sees a partial file. See
# docs/runbooks/flood.html.
#
# Run two ways, same code path (single-flight via flock so they can't race):
#   - ofelia tick every minute (steady-state file-at-a-time delivery)
#   - the event.download.finished hook (immediate pass after extraction)
#
# Completion signal per file:
#   - torrent-member files (loose .mkv): complete when
#     f.completed_chunks == f.size_chunks. size_chunks counts the partial
#     boundary chunks a file shares with neighbours, so equality means
#     every byte is downloaded and hash-verified on disk.
#   - extracted files (RAR output, not torrent members): complete when the
#     rtorrent-extract.sh `_unpackerred.*` marker is present in their dir.
#
# Hardlink, not move: the file is still a live torrent member, so rtorrent
# keeps seeding the original from /data/torrents while Plex reads the
# library link. All links to an inode are peers — single copy on disk,
# and deleting the torrent side later leaves the library link intact.

import fcntl
import os
import socket
import sys
import time
import xmlrpc.client

SOCK = "/tmp/rtorrent.sock"
DOWNLOAD_ROOT = "/data/torrents"
LOG_FILE = "/flood-db/flood-publish.log"
LOCK_FILE = "/flood-db/flood-publish.lock"
EXTRACT_MARKER_PREFIX = "_unpackerred."
GAP_GRACE_SECONDS = 2 * 3600  # don't flag a just-finished torrent as a gap

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".m4v", ".ts", ".m2ts",
    ".mov", ".wmv", ".mpg", ".mpeg",
}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}
MEDIA_EXTS = VIDEO_EXTS | SUBTITLE_EXTS


def log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S %Z"), msg), flush=True)


# --- SCGI / XML-RPC transport ---------------------------------------
# rtorrent speaks XML-RPC framed in SCGI over the local unix socket. No
# stdlib does SCGI framing, so we hand-roll the (tiny, fixed) netstring
# header; the XML-RPC marshalling itself is stdlib xmlrpc.client.

def _scgi_call(payload):
    headers = b"CONTENT_LENGTH\x00%d\x00SCGI\x001\x00" % len(payload)
    request = b"%d:%s,%s" % (len(headers), headers, payload)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    try:
        s.sendall(request)
        chunks = []
        while True:
            buf = s.recv(65536)
            if not buf:
                break
            chunks.append(buf)
    finally:
        s.close()
    resp = b"".join(chunks)
    sep = resp.find(b"\r\n\r\n")
    body = resp[sep + 4:] if sep != -1 else resp[resp.find(b"\n\n") + 2:]
    return body


def rpc(method, *params):
    payload = xmlrpc.client.dumps(params, methodname=method).encode("utf-8")
    return xmlrpc.client.loads(_scgi_call(payload))[0][0]


# --- publishing -----------------------------------------------------

def is_media(path):
    name = os.path.basename(path).lower()
    if "sample" in name:
        return False
    return os.path.splitext(name)[1] in MEDIA_EXTS


def has_extract_marker(directory):
    try:
        return any(n.startswith(EXTRACT_MARKER_PREFIX) for n in os.listdir(directory))
    except OSError:
        return False


def publish_file(src, dest):
    """Hardlink src -> dest. Returns 'linked', 'present', or 'conflict'."""
    if os.path.exists(dest):
        if os.path.samefile(src, dest):
            return "present"
        log("CONFLICT: %s exists with different inode, not overwriting" % dest)
        return "conflict"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.link(src, dest)
    log("linked %s -> %s" % (src, dest))
    return "linked"


def _iter_files(base_path):
    if os.path.isfile(base_path):  # single-file torrent
        yield base_path
        return
    for root, _dirs, files in os.walk(base_path):
        for name in files:
            yield os.path.join(root, name)


def _dest_for(src, base_path, publishdir):
    # Single-file torrent: base_path is the file itself and publishdir is its
    # parent directory, so append the filename.
    if os.path.isfile(base_path):
        return os.path.join(publishdir, os.path.basename(base_path))
    # Multi-file: publishdir and base_path are parallel per-torrent roots —
    # rtorrent appends the torrent name to both the user's chosen destination
    # (captured as publishdir) and our /data/torrents reset (base_path) — so
    # map the file's path within base_path directly under publishdir.
    return os.path.join(publishdir, os.path.relpath(src, base_path))


def process_torrent(thash, base_path, publishdir):
    """Publish every complete media file under one torrent into publishdir.

    Keyed off base_path (unique per torrent) because all redirected
    downloads share /data/torrents as their directory. Returns
    (pending, published): pending is media that can't publish yet
    (incomplete, awaiting extraction, or link conflict); published is media
    files now present in the library.
    """
    # Per-file completion for torrent members, keyed by absolute path so a
    # loose .mkv member is matched against the filesystem walk and never
    # misclassified as extracted output. f.frozen_path is the absolute path;
    # f.path is only the path *relative* to base_path (the bug that made every
    # non-RAR member look like a non-member and never publish).
    members = {}
    for frozen, completed, size_chunks in rpc(
        "f.multicall", thash, "", "f.frozen_path=", "f.completed_chunks=", "f.size_chunks="
    ):
        members[os.path.normpath(frozen)] = (int(completed) == int(size_chunks))

    pending = published = 0
    for src in _iter_files(base_path):
        if not is_media(src):
            continue
        key = os.path.normpath(src)
        if key in members:
            complete = members[key]
        else:
            complete = has_extract_marker(os.path.dirname(src))  # extracted output
        if not complete:
            pending += 1
            continue
        if publish_file(src, _dest_for(src, base_path, publishdir)) == "conflict":
            pending += 1
        else:
            published += 1
    return pending, published


def main():
    lock = None
    try:
        lock = open(LOCK_FILE, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # another pass holds the lock; it sees the same state
    except OSError as exc:
        # Lock unopenable (e.g. stale cross-uid ownership). Publishing is
        # idempotent via inode dedup, so run without single-flight rather
        # than abort the whole pass.
        log("WARN: single-flight lock unavailable (%s); continuing" % exc)

    rows = rpc(
        "d.multicall2", "", "main",
        "d.hash=", "d.base_path=", "d.custom=publishdir",
        "d.complete=", "d.custom=pubdone",
    )
    for thash, base_path, publishdir, complete, pubdone in rows:
        # Only act on redirected torrents — their data lives under
        # /data/torrents/<name>. Grandfathered torrents still in the library
        # have a non-/data/torrents base_path and are left alone.
        if not base_path.startswith(DOWNLOAD_ROOT + "/"):
            continue
        # No destination, or the bare default: left in the working dir by
        # design (nothing to publish).
        if not publishdir or publishdir == DOWNLOAD_ROOT:
            continue
        # A destination set *under* /data/torrents can't be a library path;
        # make the mistake loud rather than silently never publishing.
        if publishdir.startswith(DOWNLOAD_ROOT + "/"):
            log("WARN: %s destination is under %s (%s) — not a library path, "
                "won't publish. Use /data/TV, /data/Movies or /data/Kids."
                % (thash, DOWNLOAD_ROOT, publishdir))
            continue
        if pubdone == "1":
            continue
        try:
            pending, published = process_torrent(thash, base_path, publishdir)
        except Exception as exc:  # one bad torrent must not abort the pass
            log("ERROR processing %s: %s" % (thash, exc))
            continue
        # Mark fully-published, completed torrents so steady-state ticks
        # stop re-walking them. Require published > 0 so a completed torrent
        # whose extraction silently failed (no media on disk) is NOT marked
        # done — it stays eligible and the daily rar-backlog monitor flags
        # it. Incomplete torrents stay eligible so newly finished files
        # publish on the next tick.
        if int(complete) == 1 and pending == 0 and published > 0:
            rpc("d.custom.set", thash, "pubdone", "1")
            rpc("d.save_full_session", thash)


def check_gaps():
    """Print one line per completed torrent whose media never published.

    A publish gap = complete + has a real publishdir + not pubdone +
    finished more than the grace period ago. Consumed by rar-backlog.sh,
    which folds it into the daily Gatus heartbeat. Prints to real stdout
    (not the log file) so the caller can capture it.
    """
    now = time.time()
    rows = rpc(
        "d.multicall2", "", "main",
        "d.hash=", "d.name=", "d.complete=",
        "d.custom=publishdir", "d.custom=pubdone", "d.timestamp.finished=",
    )
    for _thash, name, complete, publishdir, pubdone, finished in rows:
        if not publishdir or publishdir.startswith(DOWNLOAD_ROOT):
            continue
        if int(complete) != 1 or pubdone == "1":
            continue
        fin = int(finished)
        if fin == 0 or (now - fin) < GAP_GRACE_SECONDS:
            continue
        print(name, flush=True)


if __name__ == "__main__":
    if "--gaps" in sys.argv:
        check_gaps()
    else:
        # Log to the file, but never let a log-open failure (e.g. a
        # cross-uid permission error) abort the run — the redirect/publish
        # work matters more than the log line. execute hooks discard the
        # fallback stdout anyway.
        try:
            sys.stdout = open(LOG_FILE, "a")
            sys.stderr = sys.stdout
        except OSError:
            pass
        try:
            main()
        except Exception as exc:
            log("FATAL: %s" % exc)
            sys.exit(1)
