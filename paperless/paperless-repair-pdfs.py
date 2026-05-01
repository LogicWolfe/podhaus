"""Repair 4 malformed PDFs via Ghostscript rewrite, then upload to Paperless
with the parent canonical page's tags + custom fields. Idempotent via sidecar.

Targets identified from the failed-uploads analysis:
  - F02.SIFMA agreement.shaded.pdf  (2 canonical parents)
  - WILLIS STREET.pdf  (2 canonical parents)
  - Scan 2020-1-30 11.51.12.pdf  (Family History - Dunham and Emma James)
  - 04. Orijin Plus, Strategic Messaging, June 2021-3.pdf
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import datetime

import requests
import yaml

SIDECAR_DB = pathlib.Path("/state/paperless-imports.sqlite")
CURATION_YAML = pathlib.Path("/state/paperless-curation.yaml")
EXPORT_ROOT = pathlib.Path("/app/output")

PAPERLESS_URL = os.environ["PAPERLESS_URL"].rstrip("/")
PAPERLESS_USERNAME = os.environ["PAPERLESS_USERNAME"]
PAPERLESS_PASSWORD = os.environ["PAPERLESS_PASSWORD"]
PAPERLESS_HOST_HEADER = os.environ.get("PAPERLESS_HOST_HEADER", "paperless.pod.haus")

# Files to repair (filename → human readable description for logs)
PDF_TARGETS = [
    "F02.SIFMA agreement.shaded.pdf",
    "WILLIS STREET.pdf",
    "Scan 2020-1-30 11.51.12.pdf",
    "04. Orijin Plus, Strategic Messaging, June 2021-3.pdf",
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def lower_tag(t: str) -> str:
    t = t.lower().strip()
    t = re.sub(r"\s+", "-", t)
    return t


def section_dropped_by_global(section, curation):
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


def compute_page_tags(page, curation):
    tags = set()
    notebook, section, title = page["notebook"], page["section"], page["title"] or ""
    nb_rule = (curation.get("notebook_tags") or {}).get(notebook) or {"action": "keep"}
    a = nb_rule.get("action", "keep")
    if a == "keep":
        tags.add(lower_tag(nb_rule.get("rename_to") or notebook))
    elif a == "rename":
        tags.add(lower_tag(nb_rule.get("rename_to")))
    for t in nb_rule.get("also_apply") or []:
        tags.add(lower_tag(t))
    sec_key = f"{notebook}/{section}" if section else None
    sec_rule = (curation.get("section_tags") or {}).get(sec_key) if sec_key else None
    if section and not section_dropped_by_global(section, curation):
        if sec_rule:
            sa = sec_rule.get("action", "keep")
            if sa == "keep":
                tags.add(lower_tag(sec_rule.get("rename_to") or section))
            elif sa == "rename":
                tags.add(lower_tag(sec_rule.get("rename_to")))
            for t in sec_rule.get("also_apply") or []:
                tags.add(lower_tag(t))
        else:
            tags.add(lower_tag(section))
    for ovr in curation.get("per_page_overrides") or []:
        if ovr.get("page_id") == page["page_id"]:
            for t in ovr.get("add_tags") or []:
                tags.add(lower_tag(t))
    for tag_name, tag_def in (curation.get("content_tags") or {}).items():
        pattern = tag_def.get("title_seed_pattern")
        if pattern:
            excludes = tag_def.get("title_seed_exclude") or []
            tlc = title.lower()
            if not any(ex.lower() in tlc for ex in excludes):
                try:
                    if re.search(pattern, title):
                        tags.add(lower_tag(tag_name))
                except re.error:
                    pass
    for rule in curation.get("tag_exclusions") or []:
        has_prefixes = rule.get("if_has_any_with_prefix") or []
        rm_prefixes = rule.get("remove_any_with_prefix") or []
        if any(any(t.startswith(p) for p in has_prefixes) for t in tags):
            tags -= {t for t in tags if any(t.startswith(p) for p in rm_prefixes)}
    return tags


def repair_pdf(src: pathlib.Path, dst: pathlib.Path) -> None:
    """Rewrite a malformed PDF through Ghostscript to produce a clean,
    Paperless-digestible version."""
    subprocess.run([
        "gs", "-o", str(dst),
        "-sDEVICE=pdfwrite",
        "-dPDFSETTINGS=/prepress",
        "-dQUIET", "-dBATCH", "-dNOPAUSE",
        "-dPDFACompatibilityPolicy=1",
        str(src),
    ], check=True, capture_output=True, timeout=180)


def paperless_session() -> requests.Session:
    s = requests.Session()
    s.headers["Host"] = PAPERLESS_HOST_HEADER
    s.headers["Accept"] = "application/json; version=5"
    r = s.post(f"{PAPERLESS_URL}/api/token/",
               data={"username": PAPERLESS_USERNAME, "password": PAPERLESS_PASSWORD},
               timeout=15)
    r.raise_for_status()
    s.headers["Authorization"] = f"Token {r.json()['token']}"
    return s


def poll_task(s, task_id, timeout_s=600):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = s.get(f"{PAPERLESS_URL}/api/tasks/?task_id={task_id}", timeout=30)
        if r.ok:
            j = r.json()
            t = (j[0] if isinstance(j, list) and j else
                 (j["results"][0] if isinstance(j, dict) and j.get("results") else None))
            if t and t.get("status") in ("SUCCESS", "FAILURE"):
                return t
        time.sleep(3)
    raise TimeoutError(task_id)


def main():
    curation = yaml.safe_load(CURATION_YAML.read_text())
    heuristic_version = curation.get("heuristic_version", 1)
    batch_id = f"pdf-repair-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    log(f"batch_id={batch_id}")

    conn = sqlite3.connect(SIDECAR_DB, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Gather target (canonical_page, asset_id, src_pdf_path) triples
    targets = []
    for pdf_name in PDF_TARGETS:
        paths = list(EXPORT_ROOT.rglob(pdf_name))
        for p in paths:
            # Path is <export_root>/<notebook>/assets/<page_id>/<filename>
            pid = p.parent.name
            page = conn.execute("SELECT * FROM pages WHERE page_id=?", (pid,)).fetchone()
            if not page:
                continue
            # Canonicalize
            if page["is_canonical"]:
                canonical = page
            elif page["canonical_page_id"]:
                canonical = conn.execute("SELECT * FROM pages WHERE page_id=?",
                                         (page["canonical_page_id"],)).fetchone()
            else:
                canonical = page
            # Look up the instance row for asset_id
            inst = conn.execute(
                "SELECT * FROM instances WHERE page_id=? AND hint_filename=?",
                (pid, pdf_name),
            ).fetchone()
            asset_id = inst["asset_id"] if inst else f"repair:{pdf_name}"
            targets.append((canonical, asset_id, p))

    # Dedup by (canonical_id, asset_id)
    seen = set()
    unique_targets = []
    for c, aid, p in targets:
        k = (c["page_id"], aid)
        if k in seen:
            continue
        seen.add(k)
        unique_targets.append((c, aid, p))
    log(f"{len(unique_targets)} unique (canonical, asset) targets to repair")

    s = paperless_session()
    log(f"auth ok: {PAPERLESS_URL}")
    # Map tags + custom fields
    tagmap = {}
    r = s.get(f"{PAPERLESS_URL}/api/tags/?page_size=500", timeout=30); r.raise_for_status()
    tagmap = {t["name"].lower(): t["id"] for t in r.json()["results"]}
    r = s.get(f"{PAPERLESS_URL}/api/custom_fields/?page_size=100", timeout=30); r.raise_for_status()
    cfmap = {f["name"]: f["id"] for f in r.json()["results"]}

    uploaded = failed = deduped = 0
    for canonical, asset_id, src in unique_targets:
        log(f"--- {canonical['title'][:40]} :: {src.name} ---")
        # Repair via Ghostscript
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            out_path = pathlib.Path(tmp.name)
        try:
            log(f"  repairing via gs → {out_path}")
            repair_pdf(src, out_path)
            sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
            log(f"  repaired: {out_path.stat().st_size} bytes  sha={sha[:16]}...")

            # Tags from canonical
            tag_names = compute_page_tags(canonical, curation)
            # Get dupes & merge
            for d in conn.execute("SELECT * FROM pages WHERE canonical_page_id=?",
                                  (canonical["page_id"],)):
                tag_names |= compute_page_tags(d, curation)
            tag_ids = [tagmap[t] for t in tag_names if t in tagmap]

            # Upload
            mt, _ = mimetypes.guess_type(str(out_path))
            with out_path.open("rb") as fh:
                files = {"document": (src.name, fh, mt or "application/pdf")}
                formdata = [("title", f"{canonical['title']} — {pathlib.Path(src.name).stem}"[:120])]
                if canonical["created"]:
                    formdata.append(("created", canonical["created"]))
                for tid in tag_ids:
                    formdata.append(("tags", str(tid)))
                r = s.post(f"{PAPERLESS_URL}/api/documents/post_document/",
                           data=formdata, files=files, timeout=180)
            if not r.ok:
                log(f"  upload FAILED {r.status_code}: {r.text[:400]}")
                failed += 1
                continue
            task_id = r.json()
            task = poll_task(s, task_id)
            if task.get("status") != "SUCCESS":
                # Check if Paperless duplicate-detected (in case we already repaired+uploaded)
                m = re.search(r"duplicate of .+ \(#(\d+)\)", task.get("result") or "")
                if m:
                    doc_id = int(m.group(1))
                    log(f"  Paperless duplicate: linking to doc#{doc_id}")
                    deduped += 1
                    conn.execute(
                        "INSERT OR IGNORE INTO uploads (paperless_doc_id, page_id, asset_id, "
                        "batch_id, heuristic_version, uploaded_at, status) VALUES (?,?,?,?,?,?,?)",
                        (doc_id, canonical["page_id"], asset_id, batch_id,
                         heuristic_version, datetime.now().isoformat(), "uploaded"))
                    continue
                log(f"  task FAILED: {task.get('result')[:300]}")
                failed += 1
                continue
            doc_id = task["related_document"]
            log(f"  → doc#{doc_id}")

            # Apply custom fields + tags
            cf_values = [
                {"field": cfmap["onenote_page_id"], "value": canonical["page_id"]},
                {"field": cfmap["onenote_canonical_page_id"], "value": canonical["page_id"]},
                {"field": cfmap["onenote_asset_kind"], "value": "pdf"},
                {"field": cfmap["content_sha256"], "value": sha},
                {"field": cfmap["import_batch"], "value": batch_id},
                {"field": cfmap["import_heuristic_version"], "value": heuristic_version},
                {"field": cfmap["onenote_resource_id"], "value": asset_id},
            ]
            if "archive_source" in cfmap:
                # not from a zip but preserve schema parity
                pass
            patch_body = {"tags": tag_ids, "custom_fields": cf_values}
            if canonical["created"]:
                patch_body["created"] = canonical["created"]
            pr = s.patch(f"{PAPERLESS_URL}/api/documents/{doc_id}/",
                         json=patch_body, timeout=30)
            if not pr.ok:
                log(f"  PATCH failed {pr.status_code}: {pr.text[:200]}")
            conn.execute(
                "INSERT OR IGNORE INTO uploads (paperless_doc_id, page_id, asset_id, "
                "batch_id, heuristic_version, uploaded_at, status) VALUES (?,?,?,?,?,?,?)",
                (doc_id, canonical["page_id"], asset_id, batch_id,
                 heuristic_version, datetime.now().isoformat(), "uploaded"))
            uploaded += 1
        except subprocess.CalledProcessError as e:
            log(f"  gs repair FAILED: {e.stderr.decode(errors='ignore')[:300]}")
            failed += 1
        except Exception as e:
            log(f"  EXCEPTION: {e}")
            failed += 1
        finally:
            out_path.unlink(missing_ok=True)
        time.sleep(1)

    log(f"DONE: {uploaded} uploaded, {deduped} deduped, {failed} failed, batch_id={batch_id}")


if __name__ == "__main__":
    main()
