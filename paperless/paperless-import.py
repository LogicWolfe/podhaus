"""Paperless Import — upload canonical OneNote pages to Paperless-ngx.

Reads:
  /state/paperless-imports.sqlite   (the audit sidecar)
  /state/paperless-curation.yaml    (the curation rules)

Writes:
  Uploads to Paperless API at $PAPERLESS_URL.
  Records each upload in the sidecar's `uploads` table for reversibility.

CLI:
  --dry-run              plan + print, no API calls
  --limit N              upload at most N canonical pages
  --notebook NB          restrict to a single notebook
  --setup-only           ensure tags + custom fields exist, then exit
  --batch-id UUID        reuse a specific batch_id (default: generate fresh)
  --heuristic-version N  override heuristic_version (default: from curation)
  --sleep-between N      seconds between uploads (be nice to OCR queue)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import datetime

import requests
import yaml

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}


def fix_image_dpi(src: pathlib.Path, dst: pathlib.Path, dpi: int = 300) -> None:
    """Copy image to dst with DPI metadata set (Paperless rejects DPI-less
    images with 'OCR_IMAGE_DPI is not set'). Flattens palette mode to RGB."""
    from PIL import Image
    with Image.open(src) as im:
        im.load()
        if im.mode == "P":
            if "transparency" in im.info:
                im = im.convert("RGBA")
            else:
                im = im.convert("RGB")
        im.save(dst, dpi=(dpi, dpi))

SIDECAR_DB = pathlib.Path("/state/paperless-imports.sqlite")
CURATION_YAML = pathlib.Path("/state/paperless-curation.yaml")
EXPORT_ROOT = pathlib.Path("/app/output")

PAPERLESS_URL = os.environ["PAPERLESS_URL"].rstrip("/")
PAPERLESS_USERNAME = os.environ["PAPERLESS_USERNAME"]
PAPERLESS_PASSWORD = os.environ["PAPERLESS_PASSWORD"]
PAPERLESS_HOST_HEADER = os.environ.get("PAPERLESS_HOST_HEADER", "paperless.pod.haus")

CUSTOM_FIELDS = [
    ("onenote_page_id", "string"),
    ("onenote_canonical_page_id", "string"),
    ("onenote_page_ids_all", "string"),  # JSON array
    ("onenote_resource_id", "string"),
    ("onenote_asset_kind", "string"),    # pdf|other_attachment|image|md_body
    ("content_sha256", "string"),
    ("import_batch", "string"),
    ("import_heuristic_version", "integer"),
]

TAG_MAP = {"auto": 6, "none": 0}  # Paperless API: 6 = MATCH_AUTO, 0 = MATCH_NONE


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------- tag computation (must match diff-plan logic) ----------------

def lower_tag(t: str) -> str:
    t = t.lower().strip()
    t = re.sub(r"\s+", "-", t)
    return t


def section_dropped_by_global(section: str | None, curation: dict) -> bool:
    if not section:
        return False
    for gr in curation.get("global_rules", []) or []:
        if gr.get("action") != "drop":
            continue
        m = gr.get("match") or {}
        if m.get("kind") == "section_regex" and re.match(m["pattern"], section):
            return True
        if m.get("kind") == "section_literal" and section == m["value"]:
            return True
    return False


def compute_page_tags(page: sqlite3.Row, curation: dict) -> dict[str, set[str]]:
    """Same logic as paperless-diff-plan.py compute_page_tags."""
    tags: dict[str, set[str]] = defaultdict(set)
    notebook = page["notebook"]
    section = page["section"]
    title = page["title"] or ""
    page_id = page["page_id"]

    # Notebook
    nb_rule = (curation.get("notebook_tags") or {}).get(notebook) or {"action": "keep"}
    a = nb_rule.get("action", "keep")
    if a == "keep":
        tags[lower_tag(nb_rule.get("rename_to") or notebook)].add(f"notebook:{notebook}")
    elif a == "rename":
        tags[lower_tag(nb_rule.get("rename_to"))].add(f"notebook:{notebook}→rename")
    for t in nb_rule.get("also_apply") or []:
        tags[lower_tag(t)].add(f"notebook:{notebook}:also_apply")

    # Section
    sec_key = f"{notebook}/{section}" if section else None
    sec_rule = (curation.get("section_tags") or {}).get(sec_key) if sec_key else None
    if section and not section_dropped_by_global(section, curation):
        if sec_rule:
            sa = sec_rule.get("action", "keep")
            if sa == "keep":
                tags[lower_tag(sec_rule.get("rename_to") or section)].add(f"section:{sec_key}")
            elif sa == "rename":
                tags[lower_tag(sec_rule.get("rename_to"))].add(f"section:{sec_key}→rename")
            for t in sec_rule.get("also_apply") or []:
                tags[lower_tag(t)].add(f"section:{sec_key}:also_apply")
        else:
            tags[lower_tag(section)].add(f"section:{sec_key}:default")

    # Per-page overrides
    for ovr in curation.get("per_page_overrides") or []:
        if ovr.get("page_id") == page_id:
            for t in ovr.get("add_tags") or []:
                tags[lower_tag(t)].add("per-page-override")
            for t in ovr.get("remove_tags") or []:
                tags.pop(lower_tag(t), None)

    # Content tag seed_pages
    for tag_name, tag_def in (curation.get("content_tags") or {}).items():
        for sp in tag_def.get("seed_pages") or []:
            matched = False
            if sp.get("page_id") and sp["page_id"] == page_id:
                matched = True
            elif sp.get("title"):
                tval = sp["title"]
                if tval == title or tval in title or title in tval:
                    matched = True
            if matched:
                tags[lower_tag(tag_name)].add(f"seed_pages:{tag_name}")
                for extra in sp.get("add_tags") or []:
                    tags[lower_tag(extra)].add(f"seed_pages:{tag_name}:add_tags")

    # Content tag title regex
    for tag_name, tag_def in (curation.get("content_tags") or {}).items():
        pattern = tag_def.get("title_seed_pattern")
        if not pattern:
            continue
        excludes = tag_def.get("title_seed_exclude") or []
        title_lc = title.lower()
        if any(ex.lower() in title_lc for ex in excludes):
            continue
        try:
            if re.search(pattern, title):
                tags[lower_tag(tag_name)].add(f"regex:{tag_name}")
        except re.error:
            pass

    return dict(tags)


def apply_tag_exclusions(tags: dict[str, set[str]], curation: dict) -> None:
    for rule in curation.get("tag_exclusions") or []:
        has_prefixes = rule.get("if_has_any_with_prefix") or []
        rm_prefixes = rule.get("remove_any_with_prefix") or []
        if not any(any(t.startswith(p) for p in has_prefixes) for t in tags):
            continue
        to_rm = [
            t for t in tags
            if any(t.startswith(p) for p in rm_prefixes)
            and "per-page-override" not in tags[t]
        ]
        for t in to_rm:
            del tags[t]


def compute_canonical_tags(
    page: sqlite3.Row,
    dupes_by_canonical: dict[str, list[sqlite3.Row]],
    curation: dict,
) -> dict[str, set[str]]:
    tags = compute_page_tags(page, curation)
    for dupe in dupes_by_canonical.get(page["page_id"], []):
        dupe_tags = compute_page_tags(dupe, curation)
        for t, srcs in dupe_tags.items():
            non_regex = {s for s in srcs if not s.startswith("regex:")}
            if non_regex:
                tags.setdefault(t, set()).add(f"dupe-merge:{dupe['notebook']}/{dupe['section']}")
    apply_tag_exclusions(tags, curation)
    if not tags and "unknown" in (curation.get("content_tags") or {}):
        tags["unknown"] = {"fallback"}
    return tags


# ---------------- Paperless API client ----------------

class Paperless:
    def __init__(self, base_url: str, username: str, password: str, host_header: str):
        self.base = base_url
        self.host_header = host_header
        self.session = requests.Session()
        self.session.headers["Host"] = host_header
        self.session.headers["Accept"] = "application/json; version=5"
        # Get token
        r = self.session.post(
            f"{base_url}/api/token/",
            data={"username": username, "password": password},
            timeout=15,
        )
        r.raise_for_status()
        self.token = r.json()["token"]
        self.session.headers["Authorization"] = f"Token {self.token}"

    def _get(self, path: str, params: dict | None = None):
        r = self.session.get(f"{self.base}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, **kwargs):
        r = self.session.post(f"{self.base}{path}", timeout=60, **kwargs)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, json_body: dict):
        r = self.session.patch(f"{self.base}{path}", json=json_body, timeout=30)
        if not r.ok:
            log(f"PATCH {path} failed {r.status_code}: {r.text[:400]}")
        r.raise_for_status()
        return r.json()

    # --- tags ---

    def list_tags(self) -> list[dict]:
        out = []
        url = f"{self.base}/api/tags/?page_size=200"
        while url:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            j = r.json()
            out.extend(j["results"])
            url = j.get("next")
        return out

    def create_tag(self, name: str, matching_algorithm: int) -> dict:
        return self._post(
            "/api/tags/",
            json={
                "name": name,
                "matching_algorithm": matching_algorithm,
                "match": "",
                "is_insensitive": True,
            },
        )

    def update_tag_matching(self, tag_id: int, matching_algorithm: int) -> None:
        self._patch(f"/api/tags/{tag_id}/", {"matching_algorithm": matching_algorithm})

    # --- custom fields ---

    def list_custom_fields(self) -> list[dict]:
        return self._get("/api/custom_fields/?page_size=100")["results"]

    def create_custom_field(self, name: str, data_type: str) -> dict:
        return self._post("/api/custom_fields/", json={"name": name, "data_type": data_type})

    # --- documents ---

    def upload_document(
        self,
        file_path: pathlib.Path,
        title: str,
        created: str | None,
        tag_ids: list[int],
    ) -> str:
        """Returns task_id."""
        mt, _ = mimetypes.guess_type(str(file_path))
        data: dict = {"title": title}
        if created:
            data["created"] = created
        if tag_ids:
            data["tags"] = tag_ids  # list form
        with file_path.open("rb") as fh:
            files = {"document": (file_path.name, fh, mt or "application/octet-stream")}
            # requests needs list of tuples for duplicate keys
            formdata = []
            for k, v in data.items():
                if isinstance(v, list):
                    for vi in v:
                        formdata.append((k, str(vi)))
                else:
                    formdata.append((k, str(v)))
            r = self.session.post(
                f"{self.base}/api/documents/post_document/",
                data=formdata,
                files=files,
                timeout=120,
            )
        if not r.ok:
            log(f"upload failed {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
        return r.json()  # task UUID string

    def poll_task(self, task_id: str, timeout_s: int = 600) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            j = self._get(f"/api/tasks/?task_id={task_id}")
            if isinstance(j, list) and j:
                t = j[0]
            elif isinstance(j, dict) and j.get("results"):
                t = j["results"][0]
            else:
                time.sleep(2)
                continue
            if t.get("status") in ("SUCCESS", "FAILURE"):
                return t
            time.sleep(3)
        raise TimeoutError(f"task {task_id} timed out")

    def set_document_fields(
        self,
        doc_id: int,
        tag_ids: list[int],
        created: str | None,
        custom_fields_values: dict[int, object],
    ) -> None:
        body: dict = {"tags": tag_ids}
        if created:
            body["created"] = created
        if custom_fields_values:
            body["custom_fields"] = [
                {"field": fid, "value": (json.dumps(v) if isinstance(v, (dict, list)) else v)}
                for fid, v in custom_fields_values.items()
            ]
        self._patch(f"/api/documents/{doc_id}/", body)


# ---------------- setup ----------------

def ensure_tags(pap: Paperless, all_tags: set[str], curation: dict) -> dict[str, int]:
    """Return tag name → id map. Creates missing tags with correct matching."""
    existing = {t["name"].lower(): t for t in pap.list_tags()}
    explicit_none = {
        n.lower()
        for n, td in (curation.get("content_tags") or {}).items()
        if (td or {}).get("matching_algorithm") == "none"
    }
    name_to_id: dict[str, int] = {}
    for name in sorted(all_tags):
        key = name.lower()
        want_alg = TAG_MAP["none"] if key in explicit_none else TAG_MAP["auto"]
        if key in existing:
            t = existing[key]
            name_to_id[name] = t["id"]
            if t["matching_algorithm"] != want_alg:
                log(f"  updating tag {name} match {t['matching_algorithm']}→{want_alg}")
                pap.update_tag_matching(t["id"], want_alg)
        else:
            log(f"  creating tag {name} (match_algorithm={want_alg})")
            t = pap.create_tag(name, want_alg)
            name_to_id[name] = t["id"]
    return name_to_id


def ensure_custom_fields(pap: Paperless) -> dict[str, int]:
    existing = {f["name"]: f for f in pap.list_custom_fields()}
    out: dict[str, int] = {}
    for name, dtype in CUSTOM_FIELDS:
        if name in existing:
            out[name] = existing[name]["id"]
        else:
            log(f"  creating custom field {name} ({dtype})")
            f = pap.create_custom_field(name, dtype)
            out[name] = f["id"]
    return out


# ---------------- upload planning ----------------

def load_dupes(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    by_canonical: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for d in conn.execute("SELECT * FROM pages WHERE canonical_page_id IS NOT NULL"):
        by_canonical[d["canonical_page_id"]].append(d)
    return by_canonical


def get_page_override(curation: dict, page_id: str) -> dict | None:
    for ovr in curation.get("per_page_overrides") or []:
        if ovr.get("page_id") == page_id:
            return ovr
    return None


def page_title(page: sqlite3.Row, curation: dict) -> str:
    ovr = get_page_override(curation, page["page_id"])
    if ovr and ovr.get("override_title"):
        return ovr["override_title"]
    return page["title"] or "(untitled)"


def planned_assets_for_page(conn: sqlite3.Connection, page_id: str) -> list[sqlite3.Row]:
    """Kept asset instances on this canonical page (pdf/other_attachment/image/md_body)."""
    return list(conn.execute(
        "SELECT * FROM instances WHERE page_id=? AND keep=1 ORDER BY kind, asset_id",
        (page_id,),
    ))


# ---------------- main ----------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--notebook", type=str, default=None)
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--batch-id", type=str, default=None)
    parser.add_argument("--heuristic-version", type=int, default=None)
    parser.add_argument("--sleep-between", type=float, default=2.0)
    args = parser.parse_args()

    curation = yaml.safe_load(CURATION_YAML.read_text())
    heuristic_version = args.heuristic_version or curation.get("heuristic_version", 1)
    batch_id = args.batch_id or str(uuid.uuid4())
    log(f"batch_id={batch_id}  heuristic_version={heuristic_version}")

    conn = sqlite3.connect(SIDECAR_DB, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    dupes_by_canonical = load_dupes(conn)
    canonical_pages = list(conn.execute(
        "SELECT * FROM pages WHERE is_canonical=1 ORDER BY notebook, section, page_id"
    ))
    if args.notebook:
        canonical_pages = [p for p in canonical_pages if p["notebook"] == args.notebook]
    if args.limit:
        canonical_pages = canonical_pages[: args.limit]
    log(f"{len(canonical_pages)} canonical pages in scope")

    # Build upload plan
    upload_plan: list[dict] = []
    all_tag_names: set[str] = set()
    for page in canonical_pages:
        tags = compute_canonical_tags(page, dupes_by_canonical, curation)
        all_tag_names.update(tags.keys())
        assets = planned_assets_for_page(conn, page["page_id"])
        title = page_title(page, curation)
        contributing_page_ids = [page["page_id"]] + [
            d["page_id"] for d in dupes_by_canonical.get(page["page_id"], [])
        ]
        upload_plan.append({
            "page": page,
            "title": title,
            "tags": sorted(tags.keys()),
            "assets": assets,
            "contributing_page_ids": contributing_page_ids,
        })

    log(f"plan: {len(upload_plan)} pages, {sum(len(p['assets']) for p in upload_plan)} assets, "
        f"{len(all_tag_names)} distinct tags")

    if args.dry_run:
        for p in upload_plan[:20]:
            log(f"  {p['title'][:70]:<70}  tags={p['tags']}  assets={len(p['assets'])}")
        if len(upload_plan) > 20:
            log(f"  ... +{len(upload_plan)-20} more")
        return

    # Auth
    log(f"auth to {PAPERLESS_URL}")
    pap = Paperless(PAPERLESS_URL, PAPERLESS_USERNAME, PAPERLESS_PASSWORD, PAPERLESS_HOST_HEADER)

    # Setup: tags + custom fields
    log("ensuring tags exist")
    tag_name_to_id = ensure_tags(pap, all_tag_names, curation)
    log("ensuring custom fields exist")
    cf_name_to_id = ensure_custom_fields(pap)

    if args.setup_only:
        log("setup-only complete")
        return

    # Build sha256 → paperless_doc_id map from prior uploads (any batch).
    # Used to short-circuit re-uploads of shared assets across canonicals.
    sha_to_doc: dict[str, int] = {}
    for r in conn.execute(
        """SELECT i.content_sha256, u.paperless_doc_id
           FROM uploads u JOIN instances i ON
             u.page_id = i.page_id AND u.asset_id = i.asset_id
           WHERE u.status='uploaded' AND i.content_sha256 IS NOT NULL"""
    ):
        sha_to_doc[r["content_sha256"]] = r["paperless_doc_id"]
    log(f"sha256 dedup map: {len(sha_to_doc)} already-uploaded assets")

    # Upload
    uploaded = 0
    skipped_dup = 0
    failed = 0
    for pi, plan in enumerate(upload_plan, 1):
        page = plan["page"]
        for asset in plan["assets"]:
            if asset["kind"] == "md_body":
                src = EXPORT_ROOT / _md_path_for_page(page)
                asset_id = "MD"
            else:
                lp = asset["local_path"]
                if not lp:
                    log(f"  SKIP asset {asset['asset_id']} for page {page['page_id']}: no local_path")
                    continue
                src = pathlib.Path(lp)
                asset_id = asset["asset_id"]
            if not src.exists():
                log(f"  SKIP {src}: file missing")
                continue

            # Paperless can't consume zip archives. Skip + log.
            if src.suffix.lower() in (".zip", ".7z", ".rar", ".gz", ".tar"):
                log(f"  SKIP {src.name}: archive file, Paperless doesn't consume these")
                continue

            # Was this asset already uploaded for this batch? Skip if so.
            prev = conn.execute(
                "SELECT paperless_doc_id FROM uploads WHERE page_id=? AND asset_id=? AND batch_id=?",
                (page["page_id"], asset_id, batch_id),
            ).fetchone()
            if prev and prev["paperless_doc_id"]:
                continue

            asset_title = _title_for_asset(plan["title"], asset, src)
            tag_ids = [tag_name_to_id[t] for t in plan["tags"] if t in tag_name_to_id]
            created = page["created"] or None
            asset_sha = asset["content_sha256"] or ""

            # DPI fix for images: Paperless rejects DPI-less PNG/JPG with
            # "OCR_IMAGE_DPI is not set" AND tesseract fails on images with
            # junk DPI values. Pre-process once to a writable tmpfile.
            upload_src = src
            _dpi_tmpfile = None
            if src.suffix.lower() in IMAGE_EXTS:
                try:
                    _dpi_tmpfile = tempfile.NamedTemporaryFile(
                        suffix=src.suffix, delete=False)
                    _dpi_tmpfile.close()
                    fix_image_dpi(src, pathlib.Path(_dpi_tmpfile.name), 300)
                    upload_src = pathlib.Path(_dpi_tmpfile.name)
                except Exception as e:
                    log(f"    WARN DPI fix failed for {src.name}: {e}")
                    upload_src = src
                    _dpi_tmpfile = None

            # --- sha256 dedup: if this file's sha was already uploaded,
            # link this page's metadata to the existing doc and skip upload.
            if asset_sha and asset_sha in sha_to_doc:
                existing_doc_id = sha_to_doc[asset_sha]
                log(f"  [{pi}/{len(upload_plan)}] DEDUP: {asset_title[:60]} shares sha with doc#{existing_doc_id}")
                conn.execute(
                    """INSERT INTO uploads (paperless_doc_id, page_id, asset_id, batch_id,
                       heuristic_version, uploaded_at, status) VALUES (?,?,?,?,?,?,?)""",
                    (existing_doc_id, page["page_id"], asset_id, batch_id,
                     heuristic_version, datetime.now().isoformat(), "uploaded"),
                )
                # Extend onenote_page_ids_all on the existing doc
                try:
                    _append_page_to_existing_doc(
                        pap, existing_doc_id, page["page_id"], cf_name_to_id)
                except Exception as e:
                    log(f"    WARN could not update onenote_page_ids_all: {e}")
                skipped_dup += 1
                continue

            try:
                log(f"  [{pi}/{len(upload_plan)}] upload: {asset_title[:60]}  ({src.name})")
                task_id = pap.upload_document(upload_src, asset_title, created, tag_ids)
                task = pap.poll_task(task_id)
                status = task.get("status")
                if status == "FAILURE":
                    # Try to extract "duplicate of NAME (#N)" from result
                    m = re.search(r"duplicate of .+ \(#(\d+)\)", task.get("result") or "")
                    if m:
                        existing_doc_id = int(m.group(1))
                        log(f"    Paperless reports duplicate; linking to existing doc#{existing_doc_id}")
                        if asset_sha:
                            sha_to_doc[asset_sha] = existing_doc_id
                        conn.execute(
                            """INSERT INTO uploads (paperless_doc_id, page_id, asset_id, batch_id,
                               heuristic_version, uploaded_at, status) VALUES (?,?,?,?,?,?,?)""",
                            (existing_doc_id, page["page_id"], asset_id, batch_id,
                             heuristic_version, datetime.now().isoformat(), "uploaded"),
                        )
                        try:
                            _append_page_to_existing_doc(
                                pap, existing_doc_id, page["page_id"], cf_name_to_id)
                        except Exception as e:
                            log(f"    WARN could not update onenote_page_ids_all: {e}")
                        skipped_dup += 1
                        continue
                    log(f"    task {task_id} FAILED: {task.get('result')}")
                    failed += 1
                    continue
                if status != "SUCCESS":
                    log(f"    task {task_id} status={status}: {task.get('result')}")
                    failed += 1
                    continue
                doc_id = task.get("related_document")
                if not doc_id:
                    log(f"    task {task_id} no related_document: {task}")
                    failed += 1
                    continue
                # Record sha → doc_id for subsequent dedup
                if asset_sha:
                    sha_to_doc[asset_sha] = doc_id

                # Apply custom fields. onenote_page_ids_all is capped at 128
                # chars (Paperless `string` limit) — if longer, store just a
                # count + first short-id instead of the full JSON array.
                page_ids_all = plan["contributing_page_ids"]
                page_ids_json = json.dumps(page_ids_all)
                if len(page_ids_json) > 128:
                    first_short = page_ids_all[0][:32] if page_ids_all else ""
                    page_ids_json = f"{len(page_ids_all)} pages, first={first_short}"[:128]
                cfv = {
                    cf_name_to_id["onenote_page_id"]: page["page_id"],
                    cf_name_to_id["onenote_canonical_page_id"]: page["page_id"],
                    cf_name_to_id["onenote_page_ids_all"]: page_ids_json,
                    cf_name_to_id["onenote_resource_id"]: asset_id,
                    cf_name_to_id["onenote_asset_kind"]: asset["kind"],
                    cf_name_to_id["content_sha256"]: asset["content_sha256"] or "",
                    cf_name_to_id["import_batch"]: batch_id,
                    cf_name_to_id["import_heuristic_version"]: heuristic_version,
                }
                pap.set_document_fields(doc_id, tag_ids, created, cfv)

                conn.execute(
                    """INSERT INTO uploads (paperless_doc_id, page_id, asset_id, batch_id,
                       heuristic_version, uploaded_at, status) VALUES (?,?,?,?,?,?,?)""",
                    (doc_id, page["page_id"], asset_id, batch_id,
                     heuristic_version, datetime.now().isoformat(), "uploaded"),
                )
                uploaded += 1
            except Exception as e:
                log(f"    EXCEPTION: {e}")
                failed += 1
            finally:
                if _dpi_tmpfile:
                    try:
                        os.unlink(_dpi_tmpfile.name)
                    except OSError:
                        pass
            time.sleep(args.sleep_between)

        if pi % 5 == 0:
            log(f"== progress: {pi}/{len(upload_plan)} pages done, {uploaded} uploaded, "
                f"{skipped_dup} deduped, {failed} failed")

    log(f"DONE: {uploaded} uploaded, {skipped_dup} deduped, {failed} failed, batch_id={batch_id}")


def _md_path_for_page(page: sqlite3.Row) -> str:
    """Locate the md file for this page within the export tree."""
    # Use the page_id to find the md file. The slug format is
    # <safe_title>-<page_id[:8]>.md in <notebook>/pages/.
    page_id = page["page_id"]
    notebook = page["notebook"].lower().replace(" ", "-").replace("'", "")
    # Just scan — not many files
    pattern = f"*-{page_id[2:8]}.md"
    candidates = list(EXPORT_ROOT.rglob(pattern))
    if not candidates:
        raise FileNotFoundError(f"no md for page {page_id}")
    return str(candidates[0].relative_to(EXPORT_ROOT))


def _append_page_to_existing_doc(
    pap: "Paperless",
    doc_id: int,
    page_id: str,
    cf_name_to_id: dict,
) -> None:
    """Append a new page_id to the existing doc's onenote_page_ids_all field."""
    r = pap.session.get(f"{pap.base}/api/documents/{doc_id}/", timeout=30)
    r.raise_for_status()
    doc = r.json()
    all_field_id = cf_name_to_id["onenote_page_ids_all"]
    existing_val = None
    for cf in doc.get("custom_fields") or []:
        if cf["field"] == all_field_id:
            existing_val = cf.get("value")
            break
    try:
        current = json.loads(existing_val) if existing_val else []
    except (json.JSONDecodeError, TypeError):
        current = []
    # Current might already be the truncated form ("N pages, first=..."); skip
    # the append in that case and just record count.
    if not isinstance(current, list):
        current = []
    if page_id not in current:
        current.append(page_id)
        val_json = json.dumps(current)
        if len(val_json) > 128:
            first_short = current[0][:32] if current else ""
            val_json = f"{len(current)} pages, first={first_short}"[:128]
        pap.set_document_fields(doc_id, doc.get("tags") or [], None,
                                {all_field_id: val_json})


def _title_for_asset(page_title: str, asset: sqlite3.Row, src: pathlib.Path) -> str:
    if asset["kind"] == "md_body":
        return page_title
    # For attachments/images, prefer the hint filename (minus extension) with
    # the page title as a prefix so the Paperless list shows context.
    hint = asset["hint_filename"] or src.name
    stem = pathlib.Path(hint).stem
    # Dedupe if title already contains stem
    if stem.lower() in page_title.lower():
        return page_title
    return f"{page_title} — {stem}"


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
