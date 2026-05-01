"""Recover OneNote page assets that were lost to the `$value` slug-collision bug.

Walks every .html file in the export dir, extracts every <img data-fullres-src>
and <object data-attachment data> resource URL, and downloads each to a
disambiguated local path under assets/<page_id>/<filename>.

Runs INSIDE the onenote-exporter container so it can reuse:
  - onenote_exporter.auth.acquire_token()  (silent MSAL refresh)
  - onenote_exporter.graph.graph_get       (existing 429/401/5xx retry logic)

Persistence:
  - Sidecar sqlite at /state/recovery.sqlite
  - Per-row commit after each download
  - Re-running with the same sidecar resumes from last incomplete row

Status:
  - Per-notebook progress during manifest build
  - Per-resource line during download
  - Periodic summary every N downloads
  - Final summary at exit
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import sqlite3
import sys
import time
from datetime import datetime
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from onenote_exporter.auth import acquire_token

EXPORT_ROOT = pathlib.Path("/app/output")
SIDECAR_DB = pathlib.Path("/state/recovery.sqlite")
GRAPH_HOST = "graph.microsoft.com"
MAX_RETRIES = 10
SUMMARY_EVERY = 50
THROTTLE_S = 1.0   # baseline inter-request sleep to be polite

SAFE_CHARS = re.compile(r'[^A-Za-z0-9._ \-()\[\]&,]')
PAGE_ID_RE = re.compile(r'^page_id:\s*(.+)$', re.MULTILINE)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------- sidecar db ----------------

def init_db(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            page_id       TEXT NOT NULL,
            resource_id   TEXT NOT NULL,
            url           TEXT NOT NULL,
            tag_kind      TEXT NOT NULL,          -- 'img' or 'object'
            hint_filename TEXT,
            hint_mime     TEXT,
            final_name    TEXT,
            local_path    TEXT,
            content_type  TEXT,
            size_bytes    INTEGER,
            sha256        TEXT,
            status        TEXT NOT NULL DEFAULT 'pending',
            error_msg     TEXT,
            last_attempt  TEXT,
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT,
            PRIMARY KEY (page_id, resource_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON downloads(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_page ON downloads(page_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    return conn


# ---------------- manifest build ----------------

def read_page_id(md_path: pathlib.Path) -> str | None:
    """Read page_id from the sibling .md file's YAML frontmatter."""
    try:
        with md_path.open("r", encoding="utf-8") as f:
            head = f.read(2048)
    except OSError:
        return None
    m = PAGE_ID_RE.search(head)
    return m.group(1).strip() if m else None


def resource_id_from_url(url: str) -> str | None:
    """Graph resource URL → resource_id ('.../resources/<id>/$value')."""
    m = re.search(r"/resources/([^/]+)/\$value", url)
    return m.group(1) if m else None


def ext_from_mime(mime: str | None) -> str:
    if not mime:
        return ".bin"
    mime = mime.split(";")[0].strip().lower()
    return {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/tiff": ".tif",
        "image/bmp": ".bmp",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "text/plain": ".txt",
        "application/zip": ".zip",
        "application/json": ".json",
        "application/octet-stream": ".bin",
    }.get(mime, ".bin")


def safe_filename(name: str, fallback: str) -> str:
    """Sanitize a filename for cross-platform safety."""
    name = name.strip()
    if not name:
        return fallback
    cleaned = SAFE_CHARS.sub("_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("._ ")
    return cleaned or fallback


def build_manifest(conn: sqlite3.Connection) -> tuple[int, int]:
    """Walk HTML files, upsert a row per (page_id, resource_id) into sqlite."""
    html_files = sorted(EXPORT_ROOT.rglob("*.html"))
    log(f"[manifest] scanning {len(html_files)} html files")

    existing = {
        (r[0], r[1]) for r in conn.execute(
            "SELECT page_id, resource_id FROM downloads WHERE status IN ('success','permanent_404')"
        )
    }

    pages_scanned = 0
    rows_added = 0
    for idx, html_path in enumerate(html_files, 1):
        md_path = html_path.with_suffix(".md")
        page_id = read_page_id(md_path) if md_path.exists() else None
        if not page_id:
            continue
        try:
            with html_path.open("r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
        except OSError:
            continue

        img_counter = 0
        seen_on_page: set[str] = set()
        for tag in soup.find_all(["img", "object"]):
            # Select the URL attribute in the same priority the exporter uses
            url = None
            for a in ("data-fullres-src", "data-src", "src", "data"):
                v = tag.get(a)
                if v and v.startswith("http") and GRAPH_HOST in v:
                    url = v
                    break
            if not url:
                continue
            res_id = resource_id_from_url(url)
            if not res_id or res_id in seen_on_page:
                continue
            seen_on_page.add(res_id)

            hint_mime = (
                tag.get("data-fullres-src-type")
                or tag.get("data-src-type")
                or tag.get("type")
                or ""
            )
            if tag.name == "object":
                hint_filename = tag.get("data-attachment", "")
                tag_kind = "object"
            else:
                img_counter += 1
                hint_filename = f"img-{img_counter:03d}{ext_from_mime(hint_mime)}"
                tag_kind = "img"

            if (page_id, res_id) in existing:
                continue

            conn.execute(
                """
                INSERT INTO downloads (page_id, resource_id, url, tag_kind, hint_filename, hint_mime, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(page_id, resource_id) DO UPDATE SET
                    url = excluded.url,
                    tag_kind = excluded.tag_kind,
                    hint_filename = excluded.hint_filename,
                    hint_mime = excluded.hint_mime
                WHERE status = 'pending'
                """,
                (page_id, res_id, url, tag_kind, hint_filename, hint_mime),
            )
            rows_added += 1

        pages_scanned += 1
        if idx % 200 == 0:
            log(f"[manifest] scanned {idx}/{len(html_files)} html files, {rows_added} new rows")

    log(f"[manifest] done — {pages_scanned} pages scanned, {rows_added} new rows added")
    return pages_scanned, rows_added


# ---------------- downloader ----------------

class Downloader:
    def __init__(self) -> None:
        self.token = acquire_token()
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self.bytes_transferred = 0
        self.completed = 0
        self.failed = 0
        self.perm_404 = 0
        self.start = time.time()

    def refresh_token(self) -> None:
        log("  [401] refreshing token")
        self.token = acquire_token()
        self.session.headers["Authorization"] = f"Bearer {self.token}"

    def stream_download(self, url: str, out_path: pathlib.Path) -> tuple[int, int, str, str]:
        """Download url to out_path with retry. Returns (status_code, size, content_type, sha256)."""
        last_err = ""
        for attempt in range(MAX_RETRIES + 1):
            try:
                with self.session.get(url, stream=True, timeout=90) as r:
                    if r.status_code == 429:
                        wait = int(r.headers.get("Retry-After", "5"))
                        log(f"  [429] sleeping {wait}s (attempt {attempt + 1}/{MAX_RETRIES + 1})")
                        time.sleep(wait)
                        continue
                    if r.status_code == 401:
                        self.refresh_token()
                        continue
                    if r.status_code == 404:
                        return 404, 0, "", ""
                    if r.status_code >= 500:
                        backoff = min(2 ** attempt, 60)
                        log(f"  [{r.status_code}] 5xx retry in {backoff}s")
                        time.sleep(backoff)
                        continue
                    if r.status_code != 200:
                        last_err = f"HTTP {r.status_code}"
                        return r.status_code, 0, "", ""

                    # Prefer Content-Disposition filename if the server provides one
                    content_type = r.headers.get("Content-Type", "")
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
                    h = hashlib.sha256()
                    size = 0
                    with tmp_path.open("wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if not chunk:
                                continue
                            f.write(chunk)
                            h.update(chunk)
                            size += len(chunk)
                    tmp_path.replace(out_path)
                    return 200, size, content_type, h.hexdigest()
            except (requests.exceptions.ReadTimeout,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError) as e:
                last_err = f"{e.__class__.__name__}: {e}"
                backoff = min(2 ** attempt, 60)
                log(f"  [net-err] {e.__class__.__name__}, retry in {backoff}s")
                time.sleep(backoff)
                continue
        raise RuntimeError(f"exhausted retries: {last_err}")

    def resolve_final_name(self, row: sqlite3.Row, conn: sqlite3.Connection) -> str:
        """Turn hint_filename into a concrete filename, disambiguating collisions in same page dir."""
        hint = row["hint_filename"] or ""
        if hint and row["tag_kind"] == "object":
            base = safe_filename(hint, f"attachment-{row['resource_id'][:8]}.bin")
        else:
            base = safe_filename(hint or f"img-{row['resource_id'][:8]}.bin",
                                  f"img-{row['resource_id'][:8]}.bin")

        # Collision check within same page
        existing = {
            r[0] for r in conn.execute(
                "SELECT final_name FROM downloads "
                "WHERE page_id = ? AND resource_id != ? AND final_name IS NOT NULL",
                (row["page_id"], row["resource_id"]),
            )
        }
        if base not in existing:
            return base
        stem, dot, ext = base.rpartition(".")
        if not dot:
            stem, ext = base, ""
        else:
            ext = "." + ext
        for n in range(2, 100):
            candidate = f"{stem}-{n}{ext}"
            if candidate not in existing:
                return candidate
        return f"{stem}-{row['resource_id'][:8]}{ext}"

    def process_row(self, row: sqlite3.Row, conn: sqlite3.Connection,
                    idx: int, total: int) -> None:
        final_name = self.resolve_final_name(row, conn)
        target = EXPORT_ROOT / self.notebook_dir_of(row["page_id"]) / "assets" / row["page_id"] / final_name

        # Idempotent skip: file on disk + previously recorded sha256 matches
        if target.exists() and row["sha256"]:
            try:
                on_disk_hash = sha256_file(target)
                if on_disk_hash == row["sha256"]:
                    conn.execute(
                        "UPDATE downloads SET status='success', final_name=?, local_path=?, updated_at=datetime('now') "
                        "WHERE page_id=? AND resource_id=?",
                        (final_name, str(target), row["page_id"], row["resource_id"]),
                    )
                    log(f"  [{idx}/{total}] skip (already downloaded): {row['page_id'][:16]}.../{final_name}")
                    return
            except OSError:
                pass

        time.sleep(THROTTLE_S)
        try:
            status, size, ctype, sha = self.stream_download(row["url"], target)
        except Exception as e:  # pragma: no cover
            conn.execute(
                "UPDATE downloads SET status='failed', error_msg=?, last_attempt=datetime('now'), updated_at=datetime('now') "
                "WHERE page_id=? AND resource_id=?",
                (str(e)[:500], row["page_id"], row["resource_id"]),
            )
            self.failed += 1
            log(f"  [{idx}/{total}] FAIL: {row['page_id'][:16]}.../{final_name}  ({e})")
            return

        if status == 404:
            conn.execute(
                "UPDATE downloads SET status='permanent_404', error_msg='Graph 404: resource does not exist', "
                "last_attempt=datetime('now'), updated_at=datetime('now') "
                "WHERE page_id=? AND resource_id=?",
                (row["page_id"], row["resource_id"]),
            )
            self.perm_404 += 1
            log(f"  [{idx}/{total}] 404: {row['page_id'][:16]}.../{final_name}")
            return

        if status != 200:
            conn.execute(
                "UPDATE downloads SET status='failed', error_msg=?, last_attempt=datetime('now'), updated_at=datetime('now') "
                "WHERE page_id=? AND resource_id=?",
                (f"HTTP {status}", row["page_id"], row["resource_id"]),
            )
            self.failed += 1
            return

        self.bytes_transferred += size
        self.completed += 1
        conn.execute(
            """
            UPDATE downloads SET status='success', final_name=?, local_path=?, content_type=?,
                size_bytes=?, sha256=?, error_msg=NULL, last_attempt=datetime('now'), updated_at=datetime('now')
            WHERE page_id=? AND resource_id=?
            """,
            (final_name, str(target), ctype, size, sha, row["page_id"], row["resource_id"]),
        )
        log(f"  [{idx}/{total}] ok: {row['page_id'][:16]}.../{final_name} ({size} B, {ctype})")

    _notebook_cache: dict[str, str] = {}

    def notebook_dir_of(self, page_id: str) -> str:
        """Which notebook directory holds this page_id? Cache by lookup."""
        if page_id in self._notebook_cache:
            return self._notebook_cache[page_id]
        for nb_dir in sorted(EXPORT_ROOT.iterdir()):
            if not nb_dir.is_dir():
                continue
            if (nb_dir / "assets" / page_id).exists():
                self._notebook_cache[page_id] = nb_dir.name
                return nb_dir.name
            # Fall back: check via md frontmatter if pages dir exists
            pages_dir = nb_dir / "pages"
            if not pages_dir.exists():
                continue
        # Last-resort scan by md frontmatter match
        for md in EXPORT_ROOT.rglob("*.md"):
            try:
                pid = read_page_id(md)
            except Exception:
                continue
            if pid == page_id:
                nb = md.parts[md.parts.index("pages") - 1]
                self._notebook_cache[page_id] = nb
                return nb
        raise RuntimeError(f"could not locate notebook for page_id {page_id}")


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------- main ----------------

def run() -> None:
    conn = init_db(SIDECAR_DB)
    log(f"sidecar db: {SIDECAR_DB}")

    build_manifest(conn)

    pending_total = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE status NOT IN ('success','permanent_404')"
    ).fetchone()[0]
    completed_before = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE status='success'"
    ).fetchone()[0]
    perm404_before = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE status='permanent_404'"
    ).fetchone()[0]
    total_rows = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]

    log(f"downloads: {total_rows} total ({completed_before} already success, "
        f"{perm404_before} permanent_404, {pending_total} to attempt)")

    if pending_total == 0:
        log("nothing to do")
        _final_summary(conn)
        return

    dl = Downloader()
    conn.row_factory = sqlite3.Row

    last_summary = time.time()
    idx = 0
    while True:
        row = conn.execute(
            "SELECT * FROM downloads WHERE status NOT IN ('success','permanent_404') "
            "ORDER BY page_id, resource_id LIMIT 1"
        ).fetchone()
        if not row:
            break
        idx += 1
        dl.process_row(row, conn, idx, pending_total)

        if idx % SUMMARY_EVERY == 0 or time.time() - last_summary > 60:
            _progress_summary(dl, conn, pending_total)
            last_summary = time.time()

    _final_summary(conn)


def _progress_summary(dl: "Downloader", conn: sqlite3.Connection, total: int) -> None:
    done = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE status='success' AND updated_at IS NOT NULL"
    ).fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='failed'").fetchone()[0]
    perm = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='permanent_404'").fetchone()[0]
    remaining = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE status NOT IN ('success','permanent_404')"
    ).fetchone()[0]
    elapsed = time.time() - dl.start
    rate = dl.completed / elapsed if elapsed > 0 else 0
    eta_s = remaining / rate if rate > 0 else 0
    mb = dl.bytes_transferred / 1024 / 1024
    log(f"=== progress: {done} success | {perm} perm_404 | {failed} failed | {remaining} remaining "
        f"| {mb:.1f} MB | {rate:.2f}/s | ETA ~{eta_s/60:.0f}m")


def _final_summary(conn: sqlite3.Connection) -> None:
    totals = dict(conn.execute(
        "SELECT status, COUNT(*) FROM downloads GROUP BY status"
    ).fetchall())
    total = sum(totals.values())
    log("===============================================================")
    log(f"=== DONE. total rows: {total}")
    for status in ("success", "permanent_404", "failed", "pending"):
        log(f"    {status:<16} {totals.get(status, 0):>5}")
    size_sum = conn.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) FROM downloads WHERE status='success'"
    ).fetchone()[0]
    log(f"    total bytes      {size_sum:>14}  ({size_sum/1024/1024:.1f} MB)")
    log("===============================================================")
    log("Next steps (NOT automatic):")
    log("  1. Verify recovery on a sample page")
    log("  2. Re-run this script to retry 'failed' rows")
    log("  3. Clean up legacy $value files after full success")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log("interrupted by user; state preserved in sidecar db")
        sys.exit(130)
