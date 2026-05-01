"""Paperless tag audit — Phase 10.0 of the OneNote → Paperless-ngx migration.

Classifies every OneNote asset (md body, PDFs, images, other attachments),
detects PDF-preview images, detects md-body noise, groups pages by content
fingerprint for cross-page dedup, and emits a reviewable tag audit YAML.

Outputs:
  /state/paperless-imports.sqlite   three-table sidecar (instances, pages, uploads)
  /state/paperless-tag-audit.yaml   human-reviewable audit view sorted by tag popularity

Runs inside the onenote-exporter container so pathing lines up with
recovery.sqlite's /app/output-rooted local_path values.

Passes:
  0  ingest pages + html assets + md bodies, join with recovery.sqlite
  A  per-page PDF-preview detection via <img data-index> attribute
  B  per-page md-body content detection (strip → length threshold)
  C  cross-page dedup by fingerprint (sha256 of sorted kept-asset shas)
  D  emit audit yaml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from datetime import datetime

import yaml
from bs4 import BeautifulSoup

EXPORT_ROOT = pathlib.Path("/app/output")
SIDECAR_DB = pathlib.Path("/state/paperless-imports.sqlite")
RECOVERY_DB = pathlib.Path("/state/recovery.sqlite")
AUDIT_YAML = pathlib.Path("/state/paperless-tag-audit.yaml")

HEURISTIC_VERSION = 1
MD_CONTENT_THRESHOLD = 200

GRAPH_HOST = "graph.microsoft.com"
RESOURCE_ID_RE = re.compile(r"/resources/([^/]+)/\$value")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
# The onenote-exporter writes unquoted `title:` values. Some OneNote page titles
# contain colons (e.g. "Fwd: Donation", "Pod Foundation: Your LITE receipt"),
# which breaks yaml.safe_load. Pre-quote before parsing.
TITLE_FIX_RE = re.compile(r"^(\s*title:\s*)(.*)$", re.MULTILINE)


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------- schema ----------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS instances (
    page_id              TEXT NOT NULL,
    asset_id             TEXT NOT NULL,
    kind                 TEXT NOT NULL,
    content_sha256       TEXT,
    keep                 INTEGER NOT NULL DEFAULT 0,
    skip_reason          TEXT,
    preview_of_asset_id  TEXT,
    hint_mime            TEXT,
    hint_filename        TEXT,
    local_path           TEXT,
    has_data_index       INTEGER NOT NULL DEFAULT 0,
    md_body_char_count   INTEGER,
    md_body_stripped_sha TEXT,
    PRIMARY KEY (page_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_instances_kind   ON instances(kind);
CREATE INDEX IF NOT EXISTS idx_instances_sha    ON instances(content_sha256);
CREATE INDEX IF NOT EXISTS idx_instances_keep   ON instances(keep);
CREATE INDEX IF NOT EXISTS idx_instances_page   ON instances(page_id);

CREATE TABLE IF NOT EXISTS pages (
    page_id              TEXT PRIMARY KEY,
    notebook             TEXT NOT NULL,
    section              TEXT,
    section_id           TEXT,
    section_group        TEXT,
    title                TEXT,
    created              TEXT,
    modified             TEXT,
    web_url              TEXT,
    fingerprint          TEXT,
    is_canonical         INTEGER NOT NULL DEFAULT 0,
    canonical_page_id    TEXT,
    heuristic_version    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_fp       ON pages(fingerprint);
CREATE INDEX IF NOT EXISTS idx_pages_can      ON pages(canonical_page_id);
CREATE INDEX IF NOT EXISTS idx_pages_notebook ON pages(notebook, section);

CREATE TABLE IF NOT EXISTS uploads (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    paperless_doc_id   INTEGER NOT NULL,
    page_id            TEXT NOT NULL,
    asset_id           TEXT NOT NULL,
    batch_id           TEXT NOT NULL,
    heuristic_version  INTEGER NOT NULL,
    uploaded_at        TEXT NOT NULL,
    status             TEXT NOT NULL,
    UNIQUE (page_id, asset_id, batch_id)
);
CREATE INDEX IF NOT EXISTS idx_uploads_doc   ON uploads(paperless_doc_id);
CREATE INDEX IF NOT EXISTS idx_uploads_batch ON uploads(batch_id);
"""


def init_sidecar(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def open_recovery_ro(path: pathlib.Path) -> sqlite3.Connection:
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- helpers ----------------

def _quote_title_if_needed(fm_text: str) -> str:
    def fix(m: re.Match) -> str:
        prefix, value = m.group(1), m.group(2)
        v = value.strip()
        if not v:
            return m.group(0)
        # Already a clean single-pair quoted string — leave as-is.
        if v[0] == '"' and v[-1] == '"' and v.count('"') == 2:
            return m.group(0)
        if v[0] == "'" and v[-1] == "'" and v.count("'") == 2:
            return m.group(0)
        # Otherwise wrap the whole value in double quotes, escaping internals.
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'{prefix}"{escaped}"'
    return TITLE_FIX_RE.sub(fix, fm_text)


def parse_frontmatter(md_path: pathlib.Path) -> tuple[dict, str]:
    with md_path.open("r", encoding="utf-8") as f:
        text = f.read()
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm = yaml.safe_load(_quote_title_if_needed(m.group(1))) or {}
    return fm, m.group(2)


def resource_id_from_url(url: str) -> str | None:
    m = RESOURCE_ID_RE.search(url)
    return m.group(1) if m else None


def kind_from_mime(mime: str | None, tag_name: str) -> str:
    if mime:
        m = mime.split(";")[0].strip().lower()
        if m == "application/pdf":
            return "pdf"
        if m.startswith("image/"):
            return "image"
        if m.startswith("application/") or m.startswith("text/"):
            return "other_attachment"
    return "image" if tag_name == "img" else "other_attachment"


def strip_md_body(body: str) -> tuple[str, int]:
    """Strip frontmatter residue, H1 heading, all ![alt](url) image lines, blank lines.
    Returns (stripped_text, char_count). Char count drives the noise threshold."""
    # Image-reference blocks in OneNote md can have multi-line alt text carrying
    # OCR garbage. Non-greedy across newlines between ![ and the closing ).
    out = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body, flags=re.DOTALL)
    out = re.sub(r"^#\s+.*$", "", out, flags=re.MULTILINE)
    out = re.sub(r"\s+", " ", out).strip()
    return out, len(out)


# ---------------- Pass 0: ingest ----------------

def ingest_page(
    sidecar: sqlite3.Connection,
    recovery_lookup: dict[tuple[str, str], sqlite3.Row],
    md_path: pathlib.Path,
    html_path: pathlib.Path,
    fm: dict,
    body: str,
) -> tuple[int, int]:
    page_id = fm.get("page_id")
    if not page_id:
        return 0, 0

    sidecar.execute(
        """INSERT INTO pages
             (page_id, notebook, section, section_id, section_group,
              title, created, modified, web_url, heuristic_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (page_id) DO UPDATE SET
             notebook=excluded.notebook,
             section=excluded.section,
             section_id=excluded.section_id,
             section_group=excluded.section_group,
             title=excluded.title,
             created=excluded.created,
             modified=excluded.modified,
             web_url=excluded.web_url,
             heuristic_version=excluded.heuristic_version""",
        (
            page_id,
            fm.get("notebook") or "UNKNOWN",
            fm.get("section"),
            str(fm.get("section_id") or "") or None,
            fm.get("section_group"),
            fm.get("title"),
            str(fm.get("created") or "") or None,
            str(fm.get("modified") or "") or None,
            fm.get("web_url"),
            HEURISTIC_VERSION,
        ),
    )

    assets_added = 0
    if html_path.exists():
        with html_path.open("r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        seen_resources: set[str] = set()
        for tag in soup.find_all(["img", "object"]):
            url = None
            for attr in ("data-fullres-src", "data-src", "src", "data"):
                v = tag.get(attr)
                if v and v.startswith("http") and GRAPH_HOST in v:
                    url = v
                    break
            if not url:
                continue
            res_id = resource_id_from_url(url)
            if not res_id or res_id in seen_resources:
                continue
            seen_resources.add(res_id)

            rec = recovery_lookup.get((page_id, res_id))
            hint_mime = (
                tag.get("data-fullres-src-type")
                or tag.get("data-src-type")
                or tag.get("type")
                or (rec["hint_mime"] if rec else "")
            )
            if tag.name == "object":
                hint_filename = tag.get("data-attachment") or (rec["hint_filename"] if rec else "")
            else:
                hint_filename = rec["hint_filename"] if rec else ""

            kind = kind_from_mime(hint_mime, tag.name)
            has_data_index = 1 if tag.get("data-index") is not None else 0
            content_sha = rec["sha256"] if rec else None
            local_path = rec["local_path"] if rec else None

            sidecar.execute(
                """INSERT INTO instances
                     (page_id, asset_id, kind, content_sha256,
                      keep, skip_reason, preview_of_asset_id,
                      hint_mime, hint_filename, local_path, has_data_index)
                   VALUES (?, ?, ?, ?, 0, NULL, NULL, ?, ?, ?, ?)
                   ON CONFLICT (page_id, asset_id) DO UPDATE SET
                     kind=excluded.kind,
                     content_sha256=excluded.content_sha256,
                     hint_mime=excluded.hint_mime,
                     hint_filename=excluded.hint_filename,
                     local_path=excluded.local_path,
                     has_data_index=excluded.has_data_index,
                     keep=0,
                     skip_reason=NULL,
                     preview_of_asset_id=NULL""",
                (page_id, res_id, kind, content_sha, hint_mime, hint_filename,
                 local_path, has_data_index),
            )
            assets_added += 1

    stripped, char_count = strip_md_body(body)
    md_sha = hashlib.sha256(stripped.encode("utf-8")).hexdigest() if char_count > 0 else None
    sidecar.execute(
        """INSERT INTO instances
             (page_id, asset_id, kind, content_sha256, keep, skip_reason,
              md_body_char_count, md_body_stripped_sha)
           VALUES (?, 'MD', 'md_body', ?, 0, NULL, ?, ?)
           ON CONFLICT (page_id, asset_id) DO UPDATE SET
             content_sha256=excluded.content_sha256,
             md_body_char_count=excluded.md_body_char_count,
             md_body_stripped_sha=excluded.md_body_stripped_sha,
             keep=0, skip_reason=NULL""",
        (page_id, md_sha, char_count, md_sha),
    )
    return 1, assets_added


def pass_0_ingest(sidecar: sqlite3.Connection, recovery: sqlite3.Connection) -> None:
    log("Pass 0: ingest pages + assets")
    md_files = sorted(EXPORT_ROOT.rglob("*.md"))
    log(f"  found {len(md_files)} md files under {EXPORT_ROOT}")

    log("  loading recovery.sqlite success rows")
    recovery_lookup: dict[tuple[str, str], sqlite3.Row] = {}
    for r in recovery.execute(
        "SELECT page_id, resource_id, sha256, hint_mime, hint_filename, local_path "
        "FROM downloads WHERE status='success'"
    ):
        recovery_lookup[(r["page_id"], r["resource_id"])] = r
    log(f"  loaded {len(recovery_lookup)} recovery rows")

    pages = 0
    assets = 0
    for idx, md_path in enumerate(md_files, 1):
        html_path = md_path.with_suffix(".html")
        try:
            fm, body = parse_frontmatter(md_path)
        except yaml.YAMLError as e:
            log(f"  SKIP invalid frontmatter in {md_path}: {e}")
            continue
        if not fm.get("page_id"):
            log(f"  SKIP no page_id in frontmatter: {md_path}")
            continue
        dp, da = ingest_page(sidecar, recovery_lookup, md_path, html_path, fm, body)
        pages += dp
        assets += da
        if idx % 100 == 0:
            log(f"  {idx}/{len(md_files)} — {pages} pages / {assets} assets indexed")

    log(f"Pass 0 done: {pages} pages, {assets} file assets")


# ---------------- Pass A: PDF preview detection ----------------

def pass_a_preview_detection(sidecar: sqlite3.Connection) -> None:
    log("Pass A: PDF preview detection (data-index signal)")

    # Start with a clean slate for keep/skip on file assets only.
    sidecar.execute(
        """UPDATE instances SET keep=0, skip_reason=NULL, preview_of_asset_id=NULL
           WHERE kind IN ('pdf','other_attachment','image')"""
    )

    # Default-keep all non-preview file assets.
    sidecar.execute(
        """UPDATE instances SET keep=1
           WHERE kind IN ('pdf','other_attachment')"""
    )
    sidecar.execute(
        """UPDATE instances SET keep=1
           WHERE kind='image' AND has_data_index=0"""
    )

    # For images WITH data-index, mark as preview. Attempt to link to parent PDF.
    pages_with_previews = sidecar.execute(
        """SELECT DISTINCT page_id FROM instances
           WHERE kind='image' AND has_data_index=1"""
    ).fetchall()

    preview_count = 0
    for pr in pages_with_previews:
        page_id = pr["page_id"]
        pdfs = sidecar.execute(
            "SELECT asset_id FROM instances WHERE page_id=? AND kind='pdf'",
            (page_id,),
        ).fetchall()
        parent = pdfs[0]["asset_id"] if len(pdfs) == 1 else "unknown_pdf_on_same_page"
        cur = sidecar.execute(
            """UPDATE instances
                 SET keep=0, skip_reason='pdf_preview', preview_of_asset_id=?
               WHERE page_id=? AND kind='image' AND has_data_index=1""",
            (parent, page_id),
        )
        preview_count += cur.rowcount

    log(f"Pass A done: flagged {preview_count} data-indexed images as pdf_preview")


# ---------------- Pass B: md content detection ----------------

def pass_b_md_content(sidecar: sqlite3.Connection) -> None:
    log("Pass B: md-body content detection")

    cur = sidecar.execute(
        f"""UPDATE instances
              SET keep=1, skip_reason=NULL
            WHERE kind='md_body' AND md_body_char_count > {MD_CONTENT_THRESHOLD}"""
    )
    kept = cur.rowcount
    cur = sidecar.execute(
        f"""UPDATE instances
              SET keep=0, skip_reason='md_noise'
            WHERE kind='md_body' AND (md_body_char_count IS NULL OR md_body_char_count <= {MD_CONTENT_THRESHOLD})"""
    )
    skipped = cur.rowcount
    log(f"Pass B done: {kept} md bodies kept, {skipped} marked noise (threshold={MD_CONTENT_THRESHOLD} chars)")


# ---------------- Pass C: fingerprint + canonical ----------------

def fingerprint_of(sha_list: list[str]) -> str | None:
    if not sha_list:
        return None
    return hashlib.sha256(
        json.dumps(sorted(sha_list), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def pass_c_dedup(sidecar: sqlite3.Connection) -> None:
    log("Pass C: fingerprint + canonical selection")

    sidecar.execute(
        "UPDATE pages SET fingerprint=NULL, is_canonical=0, canonical_page_id=NULL"
    )

    # Accumulate per-page kept-asset sha lists in one SQL pass.
    by_page: dict[str, list[str]] = {}
    for r in sidecar.execute(
        """SELECT page_id, content_sha256 FROM instances
           WHERE keep=1 AND content_sha256 IS NOT NULL"""
    ):
        by_page.setdefault(r["page_id"], []).append(r["content_sha256"])

    by_fp: dict[str, list[str]] = {}
    for page_id, shas in by_page.items():
        fp = fingerprint_of(shas)
        if fp is None:
            continue
        sidecar.execute("UPDATE pages SET fingerprint=? WHERE page_id=?", (fp, page_id))
        by_fp.setdefault(fp, []).append(page_id)

    canon = 0
    dupes = 0
    for page_ids in by_fp.values():
        # Canonical = earliest `created` then lowest page_id as deterministic tiebreaker.
        # `created` is Evernote-era for most pages, migration-artifact only for 7 of 1060.
        rows = sidecar.execute(
            f"SELECT page_id, COALESCE(created, '') AS created FROM pages "
            f"WHERE page_id IN ({','.join('?' * len(page_ids))})",
            page_ids,
        ).fetchall()
        canonical = sorted(rows, key=lambda r: (r["created"], r["page_id"]))[0]["page_id"]
        sidecar.execute("UPDATE pages SET is_canonical=1 WHERE page_id=?", (canonical,))
        canon += 1
        for p in page_ids:
            if p != canonical:
                sidecar.execute(
                    "UPDATE pages SET canonical_page_id=? WHERE page_id=?",
                    (canonical, p),
                )
                dupes += 1

    no_content = sidecar.execute(
        "SELECT COUNT(*) AS n FROM pages WHERE fingerprint IS NULL"
    ).fetchone()["n"]
    log(f"Pass C done: {canon} canonical / {dupes} dupes / {no_content} no-upload pages")


# ---------------- Pass D: emit tag audit yaml ----------------

def emit_audit_yaml(sidecar: sqlite3.Connection, path: pathlib.Path) -> None:
    log(f"Pass D: emitting audit yaml to {path}")

    summary = {
        "heuristic_version": HEURISTIC_VERSION,
        "md_content_threshold": MD_CONTENT_THRESHOLD,
        "total_pages": sidecar.execute(
            "SELECT COUNT(*) AS n FROM pages"
        ).fetchone()["n"],
        "total_canonical_pages": sidecar.execute(
            "SELECT COUNT(*) AS n FROM pages WHERE is_canonical=1"
        ).fetchone()["n"],
        "total_no_upload_pages": sidecar.execute(
            "SELECT COUNT(*) AS n FROM pages WHERE fingerprint IS NULL"
        ).fetchone()["n"],
        "total_dedup_groups_size_2plus": sidecar.execute(
            """SELECT COUNT(*) AS n FROM (
                 SELECT fingerprint FROM pages WHERE fingerprint IS NOT NULL
                  GROUP BY fingerprint HAVING COUNT(*) > 1)"""
        ).fetchone()["n"],
        "total_assets_kept": sidecar.execute(
            "SELECT COUNT(*) AS n FROM instances WHERE keep=1"
        ).fetchone()["n"],
        "total_assets_skipped_preview": sidecar.execute(
            "SELECT COUNT(*) AS n FROM instances WHERE skip_reason='pdf_preview'"
        ).fetchone()["n"],
        "total_assets_skipped_noise": sidecar.execute(
            "SELECT COUNT(*) AS n FROM instances WHERE skip_reason='md_noise'"
        ).fetchone()["n"],
        "kind_breakdown": {
            r["kind"]: {"total": r["total"], "kept": r["kept"] or 0}
            for r in sidecar.execute(
                """SELECT kind, COUNT(*) AS total, SUM(keep) AS kept
                   FROM instances GROUP BY kind ORDER BY kind"""
            )
        },
    }

    rows = sidecar.execute(
        """SELECT notebook, section, page_id, title, is_canonical, canonical_page_id, fingerprint
           FROM pages WHERE notebook IS NOT NULL"""
    ).fetchall()

    tags: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["notebook"], r["section"] or "")
        entry = tags.setdefault(key, {"canonical": [], "dupes": [], "no_content": []})
        if r["is_canonical"]:
            entry["canonical"].append(r)
        elif r["canonical_page_id"]:
            entry["dupes"].append(r)
        else:
            entry["no_content"].append(r)

    tag_list = []
    for (nb, sec), entry in tags.items():
        name = f"{nb}/{sec}" if sec else nb
        tag_list.append({
            "name": name,
            "notebook": nb,
            "section": sec,
            "canonical_page_count": len(entry["canonical"]),
            "dupe_page_count": len(entry["dupes"]),
            "no_content_page_count": len(entry["no_content"]),
            "canonical_pages": [
                {"page_id": r["page_id"], "title": r["title"] or ""}
                for r in sorted(entry["canonical"], key=lambda x: x["page_id"])
            ],
            "dupe_pages": [
                {
                    "page_id": r["page_id"],
                    "title": r["title"] or "",
                    "canonical_page_id": r["canonical_page_id"],
                }
                for r in sorted(entry["dupes"], key=lambda x: x["page_id"])
            ],
            "no_content_pages": [
                {"page_id": r["page_id"], "title": r["title"] or ""}
                for r in sorted(entry["no_content"], key=lambda x: x["page_id"])
            ],
        })
    tag_list.sort(key=lambda t: (-t["canonical_page_count"], t["name"]))
    summary["total_distinct_tags"] = len(tag_list)

    header = (
        "# Generated by paperless-tag-audit.py — read-only audit view.\n"
        "# Curation plan lives in paperless-curation.yaml (authored separately).\n"
        f"# Generated: {datetime.now().isoformat(timespec='seconds')}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump({"summary": summary, "tags": tag_list},
                       f, sort_keys=False, allow_unicode=True, width=120)

    log(f"  wrote {len(tag_list)} tags, top-5 by canonical count:")
    for t in tag_list[:5]:
        log(f"    {t['name']:<40}  canon={t['canonical_page_count']:<4} dupes={t['dupe_page_count']}")


# ---------------- main ----------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Paperless tag audit — Phase 10.0")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run Pass 0 only, skip classification and yaml emission.")
    args = parser.parse_args()

    log(f"sidecar db: {SIDECAR_DB}")
    log(f"recovery db: {RECOVERY_DB}")
    if not RECOVERY_DB.exists():
        log(f"FATAL: recovery.sqlite missing at {RECOVERY_DB}")
        sys.exit(1)
    if not EXPORT_ROOT.exists():
        log(f"FATAL: export root missing at {EXPORT_ROOT}")
        sys.exit(1)

    sidecar = init_sidecar(SIDECAR_DB)
    recovery = open_recovery_ro(RECOVERY_DB)

    try:
        pass_0_ingest(sidecar, recovery)
        if args.dry_run:
            log("DRY RUN: stopping after Pass 0")
            return
        pass_a_preview_detection(sidecar)
        pass_b_md_content(sidecar)
        pass_c_dedup(sidecar)
        emit_audit_yaml(sidecar, AUDIT_YAML)

        log("=" * 60)
        log("Final per-kind summary:")
        for r in sidecar.execute(
            """SELECT kind, COUNT(*) AS total, SUM(keep) AS kept
               FROM instances GROUP BY kind ORDER BY kind"""
        ):
            log(f"  {r['kind']:<18} total={r['total']:<6} kept={r['kept']}")
        row = sidecar.execute(
            "SELECT COUNT(*) AS n FROM pages WHERE is_canonical=1"
        ).fetchone()
        log(f"  canonical pages = {row['n']}")
        log("=" * 60)
    finally:
        sidecar.close()
        recovery.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
