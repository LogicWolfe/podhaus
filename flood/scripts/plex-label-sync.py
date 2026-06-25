#!/usr/bin/env python3
# Mirrors each torrent's Flood tags onto the matching Plex show/movie as
# Plex Labels, so a torrent tagged "indigo"/"rowan" grants that managed
# user access to the title (Plex label-based content restrictions; the
# user's restriction profile must be set to None for label filtering to
# apply — a one-time per-user setup in Plex, see docs/runbooks/flood.html).
#
# Generic by design: every tag becomes a label, no hardcoded tag list. A
# new kid/category is zero code change — tag torrents, add the label to
# that user's allow-list in Plex. "pinelake" rides along harmlessly.
#
# Why it lives in flood: this container already holds the tags (rtorrent
# d.custom1) AND the publish-path logic, and reaches host-network Plex
# over the dockernet gateway (172.18.0.1:32400) — the same path Cloudflare
# Tunnel uses for host-network services.
#
# Trigger model mirrors pinelake-stignore (tags get applied at add-time,
# mid-download, or after completion):
#   - rtorrent event.download.finished hook (zero-latency on completion)
#   - ofelia tick every 5 min (catches tag-applied-after-completion and is
#     the workhorse, since Plex's own library scan lags the publish)
#
# Additive-only: removing a tag never strips the label (won't fight labels
# set by hand in Plex). Access is revoked manually.
#
# Steady-state cheap: each torrent's applied tag-set is stashed in the
# d.custom "labelsync" field. A tick that finds the current tags already
# == labelsync skips the torrent entirely (no Plex round-trip). Plex is
# only contacted when a torrent's tags actually changed since last sync.
#
# Label granularity is the *show* (for TV) or the *movie* — the only level
# Plex's sharing label restrictions filter on. A tagged episode labels its
# whole show.

import fcntl
import importlib.util
import os
import sys
import time
import urllib.parse
import urllib.request

LOG_FILE = "/flood-db/plex-label-sync.log"
LOCK_FILE = "/flood-db/plex-label-sync.lock"
DOWNLOAD_ROOT = "/data/torrents"
# flood mounts MEDIA_DIR at /data; plex mounts the same MEDIA_DIR at
# /Users/Shared/Pouch. The physical file is identical — only the mount
# prefix differs, so a published path is translated prefix-for-prefix into
# the path Plex indexes (Media.Part.file).
FLOOD_MEDIA_ROOT = os.environ.get("FLOOD_MEDIA_ROOT", "/data")
PLEX_MEDIA_ROOT = os.environ.get("PLEX_MEDIA_ROOT", "/Users/Shared/Pouch")
GATUS_ENDPOINT = "http://gatus:8080/api/v1/endpoints/torrents_plex-label-sync/external"


def log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S %Z"), msg), flush=True)


# Reuse flood-publish's rtorrent transport + publish-path logic verbatim so
# the two never drift on how a download member maps to its library path.
# The hyphen in the filename blocks a normal import; load it by path. Safe
# to import (all side effects are under its __main__ guard).
_spec = importlib.util.spec_from_file_location(
    "flood_publish", os.path.join(os.path.dirname(os.path.abspath(__file__)), "flood-publish.py")
)
flood_publish = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flood_publish)
rpc = flood_publish.rpc


def parse_tags(custom1):
    """rtorrent d.custom1 is a URL-encoded CSV of Flood tags."""
    tags = []
    for raw in custom1.split(","):
        tag = urllib.parse.unquote(raw).strip()
        if tag:
            tags.append(tag)
    return sorted(set(tags))


def translate_to_plex(path):
    """Map a flood-side library path to the path Plex indexes."""
    if path == FLOOD_MEDIA_ROOT or path.startswith(FLOOD_MEDIA_ROOT + "/"):
        return PLEX_MEDIA_ROOT + path[len(FLOOD_MEDIA_ROOT):]
    return None


def published_video_paths(thash, base_path, publishdir):
    """Plex-side paths of this torrent's published *video* files that exist.

    Subtitles are excluded — Plex doesn't index them as items, so they can
    never resolve and would otherwise wedge a torrent permanently
    'unresolved'. Reuses flood-publish's completion + destination logic.
    """
    members = {}
    for frozen, completed, size_chunks in rpc(
        "f.multicall", thash, "", "f.frozen_path=", "f.completed_chunks=", "f.size_chunks="
    ):
        members[os.path.normpath(frozen)] = (int(completed) == int(size_chunks))

    paths = []
    for src in flood_publish._iter_files(base_path):
        if os.path.splitext(src.lower())[1] not in flood_publish.VIDEO_EXTS:
            continue
        if "sample" in os.path.basename(src).lower():
            continue
        key = os.path.normpath(src)
        complete = members[key] if key in members else flood_publish.has_extract_marker(os.path.dirname(src))
        if not complete:
            continue
        dest = flood_publish._dest_for(src, base_path, publishdir)
        if not os.path.exists(dest):  # not published into the library yet
            continue
        plex_path = translate_to_plex(dest)
        if plex_path:
            paths.append(plex_path)
    return paths


# --- Plex side ------------------------------------------------------
# A thin lazy index so Plex is only ever touched when there's real work,
# and each library section is fetched at most once per run.

class PlexResolver:
    def __init__(self):
        from plexapi.server import PlexServer  # imported lazily — only on real work

        url = os.environ["PLEX_URL"]
        token = os.environ["PLEX_TOKEN"]
        self._server = PlexServer(url, token)
        # (location-prefix, section) for every movie/show library, so a
        # path resolves to exactly one section by longest-prefix match.
        self._sections = []
        for section in self._server.library.sections():
            if section.type in ("movie", "show"):
                for loc in section.locations:
                    self._sections.append((loc.rstrip("/") + "/", section))
        self._file_index = {}   # section.key -> {plex_file_path: item}
        self._show_cache = {}    # grandparentRatingKey -> Show

    def _section_for(self, plex_path):
        best = None
        for prefix, section in self._sections:
            if plex_path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                best = (prefix, section)
        return best[1] if best else None

    def _index(self, section):
        if section.key in self._file_index:
            return self._file_index[section.key]
        libtype = "movie" if section.type == "movie" else "episode"
        index = {}
        for item in section.search(libtype=libtype):
            for media in item.media:
                for part in media.parts:
                    index[part.file] = item
        self._file_index[section.key] = index
        return index

    def target_for(self, plex_path):
        """The Plex Show/Movie a published file belongs to, or None if Plex
        hasn't indexed the file yet."""
        section = self._section_for(plex_path)
        if section is None:
            return None
        item = self._index(section).get(plex_path)
        if item is None:
            return None
        if section.type == "movie":
            return item
        # episode -> its show (cached; one fetch per show per run)
        if item.grandparentRatingKey not in self._show_cache:
            self._show_cache[item.grandparentRatingKey] = item.show()
        return self._show_cache[item.grandparentRatingKey]


def apply_labels(target, tags):
    existing = {label.tag for label in target.labels}
    missing = [t for t in tags if t not in existing]
    if missing:
        target.addLabel(missing)
        log("labeled %s '%s' += %s" % (target.type, target.title, ",".join(missing)))


def sync_torrent(resolver, thash, base_path, publishdir, tags):
    """Returns True if every published video resolved and labels are applied
    (so the torrent can be marked done), False to retry next tick."""
    video_paths = published_video_paths(thash, base_path, publishdir)
    if not video_paths:
        return False  # nothing published/scannable yet
    targets = {}
    for plex_path in video_paths:
        target = resolver.target_for(plex_path)
        if target is None:
            return False  # Plex hasn't indexed this file yet — retry later
        targets[target.ratingKey] = target
    for target in targets.values():
        apply_labels(target, tags)
    return True


def main():
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # another pass holds the lock; it sees the same state

    rows = rpc(
        "d.multicall2", "", "main",
        "d.hash=", "d.base_path=", "d.custom=publishdir",
        "d.custom1=", "d.custom=labelsync",
    )

    # First, the cheap pass: which torrents actually need Plex work?
    pending = []
    for thash, base_path, publishdir, custom1, labelsync in rows:
        if not base_path.startswith(DOWNLOAD_ROOT + "/"):
            continue
        if not publishdir or publishdir == DOWNLOAD_ROOT or publishdir.startswith(DOWNLOAD_ROOT + "/"):
            continue
        tags = parse_tags(custom1)
        if not tags:
            continue
        current = ",".join(tags)
        if labelsync == current:
            continue  # these exact tags already mirrored — no Plex round-trip
        pending.append((thash, base_path, publishdir, tags, current))

    if not pending:
        return  # steady state: nothing changed, Plex untouched

    # A Plex outage must not suppress the heartbeat — its job is detecting
    # whether ofelia is still ticking us, not Plex's health (Plex has its own
    # monitor, and an unset labelsync means the next tick simply retries once
    # Plex is back). So the whole Plex phase is best-effort: log and move on.
    try:
        resolver = PlexResolver()
    except Exception as exc:
        log("WARN: Plex unreachable (%s); %d torrent(s) deferred to next tick"
            % (exc, len(pending)))
        return
    for thash, base_path, publishdir, tags, current in pending:
        try:
            done = sync_torrent(resolver, thash, base_path, publishdir, tags)
        except Exception as exc:  # one bad torrent must not abort the pass
            log("ERROR syncing %s: %s" % (thash, exc))
            continue
        if done:
            rpc("d.custom.set", thash, "labelsync", current)
            rpc("d.save_full_session", thash)


def heartbeat():
    token = os.environ.get("GATUS_OFELIA_PUSH_TOKEN")
    if not token:
        return
    req = urllib.request.Request(
        GATUS_ENDPOINT + "?success=true", data=b"", method="POST",
        headers={"Authorization": "Bearer " + token},
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:
        log("WARN: gatus heartbeat push failed: %s" % exc)


if __name__ == "__main__":
    try:
        sys.stdout = open(LOG_FILE, "a")
        sys.stderr = sys.stdout
    except OSError:
        pass
    try:
        main()
    except Exception as exc:
        log("FATAL: %s" % exc)
        sys.exit(1)  # no heartbeat → Gatus dead-man's switch fires
    heartbeat()
