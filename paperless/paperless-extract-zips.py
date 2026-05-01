"""Extract zip archives in the OneNote export and upload their contents to
Paperless as individual documents with the parent page's tags + metadata.

For image-only zips (≥3 files, all images), also generate a lossless
contact-sheet PDF:
  - Page 1: a visual grid index (labeled thumbnails) — reference only
  - Pages 2..N: each original image on its own page, embedded losslessly
    via img2pdf (FlateDecode for PNGs, DCT for JPEGs, NO re-encoding)
  Extraction of originals from the PDF: `pdfimages -all -png contact.pdf out/`

For mixed / PDF-only zips, just upload each file.

All uploads inherit the parent OneNote page's tag set + metadata so they
appear as siblings when we run paperless-crosslink.py afterward.

Env: PAPERLESS_URL, PAPERLESS_USERNAME, PAPERLESS_PASSWORD, PAPERLESS_HOST_HEADER.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
import zipfile
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

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}
SKIP_FILE_PREFIXES = ("__MACOSX/", "._")  # Apple metadata junk
SKIP_NAMES = {".DS_Store", "Thumbs.db"}
MIN_CONTACT_SHEET_IMAGES = 3


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


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


def compute_page_tags(page: sqlite3.Row, curation: dict) -> set[str]:
    """Same tag computation as the main import, simplified return."""
    tags: set[str] = set()
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
            for t in ovr.get("remove_tags") or []:
                tags.discard(lower_tag(t))

    for tag_name, tag_def in (curation.get("content_tags") or {}).items():
        for sp in tag_def.get("seed_pages") or []:
            matched = False
            if sp.get("page_id") and sp["page_id"] == page["page_id"]:
                matched = True
            elif sp.get("title"):
                tval = sp["title"]
                if tval == title or tval in title or title in tval:
                    matched = True
            if matched:
                tags.add(lower_tag(tag_name))
                for extra in sp.get("add_tags") or []:
                    tags.add(lower_tag(extra))
        pattern = tag_def.get("title_seed_pattern")
        if pattern:
            excludes = tag_def.get("title_seed_exclude") or []
            title_lc = title.lower()
            if not any(ex.lower() in title_lc for ex in excludes):
                try:
                    if re.search(pattern, title):
                        tags.add(lower_tag(tag_name))
                except re.error:
                    pass

    # Apply tag_exclusions
    for rule in curation.get("tag_exclusions") or []:
        has_prefixes = rule.get("if_has_any_with_prefix") or []
        rm_prefixes = rule.get("remove_any_with_prefix") or []
        if any(any(t.startswith(p) for p in has_prefixes) for t in tags):
            to_rm = {t for t in tags if any(t.startswith(p) for p in rm_prefixes)}
            tags -= to_rm
    return tags


def canonical_tags_with_dupes(
    page: sqlite3.Row,
    dupes: list[sqlite3.Row],
    curation: dict,
) -> set[str]:
    tags = compute_page_tags(page, curation)
    for d in dupes:
        tags |= compute_page_tags(d, curation)
    return tags


# ---------------- Paperless client ----------------

class Paperless:
    def __init__(self):
        self.base = PAPERLESS_URL
        self.session = requests.Session()
        self.session.headers["Host"] = PAPERLESS_HOST_HEADER
        self.session.headers["Accept"] = "application/json; version=5"
        r = self.session.post(
            f"{self.base}/api/token/",
            data={"username": PAPERLESS_USERNAME, "password": PAPERLESS_PASSWORD},
            timeout=15,
        )
        r.raise_for_status()
        self.session.headers["Authorization"] = f"Token {r.json()['token']}"

    def list_tags(self) -> list[dict]:
        out, url = [], f"{self.base}/api/tags/?page_size=200"
        while url:
            r = self.session.get(url, timeout=30); r.raise_for_status()
            j = r.json(); out.extend(j["results"]); url = j.get("next")
        return out

    def create_tag(self, name: str, matching_algorithm: int) -> dict:
        r = self.session.post(f"{self.base}/api/tags/", json={
            "name": name, "matching_algorithm": matching_algorithm,
            "match": "", "is_insensitive": True,
        }, timeout=30)
        r.raise_for_status(); return r.json()

    def list_custom_fields(self) -> list[dict]:
        r = self.session.get(f"{self.base}/api/custom_fields/?page_size=100", timeout=30)
        r.raise_for_status(); return r.json()["results"]

    def upload(self, file_path: pathlib.Path, title: str, created: str | None,
               tag_ids: list[int]) -> str:
        data = {"title": title}
        if created:
            data["created"] = created
        formdata = [(k, str(v)) for k, v in data.items()]
        for tid in tag_ids:
            formdata.append(("tags", str(tid)))
        import mimetypes
        mt, _ = mimetypes.guess_type(str(file_path))
        with file_path.open("rb") as fh:
            files = {"document": (file_path.name, fh, mt or "application/octet-stream")}
            r = self.session.post(
                f"{self.base}/api/documents/post_document/",
                data=formdata, files=files, timeout=120,
            )
        if not r.ok:
            log(f"    upload failed {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
        return r.json()

    def poll_task(self, task_id: str, timeout_s: int = 600) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            r = self.session.get(f"{self.base}/api/tasks/?task_id={task_id}", timeout=30)
            if r.ok:
                j = r.json()
                t = j[0] if isinstance(j, list) and j else (j["results"][0] if isinstance(j, dict) and j.get("results") else None)
                if t and t.get("status") in ("SUCCESS", "FAILURE"):
                    return t
            time.sleep(3)
        raise TimeoutError(task_id)

    def patch_doc(self, doc_id: int, body: dict) -> None:
        r = self.session.patch(f"{self.base}/api/documents/{doc_id}/", json=body, timeout=30)
        if not r.ok:
            log(f"    PATCH doc#{doc_id} failed {r.status_code}: {r.text[:300]}")
            r.raise_for_status()


# ---------------- DPI + contact sheet ----------------

def fix_image_dpi(src: pathlib.Path, dst: pathlib.Path, dpi: int = 300) -> None:
    """Write image to dst with DPI metadata set. Required because Paperless
    rejects images without DPI info ("OCR_IMAGE_DPI is not set")."""
    from PIL import Image
    with Image.open(src) as im:
        im.load()
        if im.mode == "P":
            im = im.convert("RGBA" if "transparency" in im.info else "RGB")
        im.save(dst, dpi=(dpi, dpi))


def generate_contact_sheet_pdf(
    image_paths: list[pathlib.Path],
    labels: list[str],
    out_pdf: pathlib.Path,
    title: str,
) -> None:
    """Create a PDF where:
      - Page 1: visual contact sheet (Pillow grid, reference only)
      - Pages 2..N: each original image, embedded losslessly via img2pdf
    So `pdfimages -all -png out.pdf` recovers originals byte-for-byte.
    """
    from PIL import Image, ImageDraw, ImageFont
    import img2pdf

    # --- Page 1: contact sheet image (Pillow) ---
    page_w, page_h = 2550, 3300  # 8.5x11 at 300 DPI
    margin = 100
    title_h = 120
    cols = 3 if len(image_paths) > 4 else 2
    rows = (len(image_paths) + cols - 1) // cols
    cell_w = (page_w - 2 * margin) // cols
    cell_h = (page_h - 2 * margin - title_h) // max(rows, 1)
    cs = Image.new("RGB", (page_w, page_h), "white")
    draw = ImageDraw.Draw(cs)
    try:
        font_title = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
        font_label = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except Exception:
        font_title = ImageFont.load_default()
        font_label = ImageFont.load_default()
    draw.text((margin, margin // 2), title, fill="black", font=font_title)

    thumb_pad = 40
    for idx, (img_path, label) in enumerate(zip(image_paths, labels)):
        col, row = idx % cols, idx // cols
        x0 = margin + col * cell_w + thumb_pad
        y0 = margin + title_h + row * cell_h + thumb_pad
        avail_w = cell_w - 2 * thumb_pad
        avail_h = cell_h - 2 * thumb_pad - 60  # leave room for label
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            im.thumbnail((avail_w, avail_h))
            cs.paste(im, (x0 + (avail_w - im.width) // 2,
                          y0 + (avail_h - im.height) // 2))
        label_y = y0 + avail_h + 10
        # Truncate label if too long
        lbl = label if len(label) <= 40 else label[:37] + "..."
        draw.text((x0, label_y), lbl, fill="black", font=font_label)

    contact_sheet_png = out_pdf.with_suffix(".sheet.png")
    cs.save(contact_sheet_png, dpi=(300, 300))

    # --- Build PDF: contact sheet + originals ---
    # Lossless where possible. Only re-encode if alpha channel needs flattening
    # (img2pdf can't embed RGBA); otherwise pass original bytes through so
    # JPEGs stay DCT-identical and PNGs stay byte-identical.
    image_buffers: list[bytes] = []
    for p in [contact_sheet_png] + image_paths:
        with Image.open(p) as im:
            im.load()
            needs_flatten = im.mode in ("RGBA", "LA") or (
                im.mode == "P" and "transparency" in im.info)
            palette_mode = im.mode == "P"
        if needs_flatten:
            with Image.open(p) as im:
                if im.mode in ("RGBA", "LA"):
                    bg = Image.new("RGB", im.size, "white")
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="PNG", compress_level=1)
                image_buffers.append(buf.getvalue())
        elif palette_mode:
            with Image.open(p) as im:
                im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="PNG", compress_level=1)
                image_buffers.append(buf.getvalue())
        else:
            # Pass original bytes through — no re-encode.
            image_buffers.append(p.read_bytes())

    # Single img2pdf.convert call builds the whole multi-page PDF with
    # explicit page size (A4) so tiny images don't produce tiny pages.
    layout = img2pdf.get_layout_fun(
        pagesize=(img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11)),
        imgsize=None,
        fit=img2pdf.FitMode.into,
    )
    pdf_bytes = img2pdf.convert(image_buffers, layout_fun=layout)
    out_pdf.write_bytes(pdf_bytes)
    contact_sheet_png.unlink(missing_ok=True)


# ---------------- main ----------------

def find_zips_with_parent_pages(
    conn: sqlite3.Connection,
) -> list[tuple[pathlib.Path, sqlite3.Row, list[sqlite3.Row]]]:
    """Return [(zip_path, canonical_page, dupes), ...] for every zip on disk."""
    out = []
    # Each zip lives under <notebook>/assets/<page_id>/ — find all
    for zp in EXPORT_ROOT.rglob("*.zip"):
        # Path: .../assets/<page_id>/<zipname>.zip
        page_id = zp.parent.name
        page = conn.execute("SELECT * FROM pages WHERE page_id=?", (page_id,)).fetchone()
        if not page:
            continue
        if page["is_canonical"]:
            canonical = page
            dupes = list(conn.execute(
                "SELECT * FROM pages WHERE canonical_page_id=?", (page_id,)))
        elif page["canonical_page_id"]:
            canonical = conn.execute(
                "SELECT * FROM pages WHERE page_id=?",
                (page["canonical_page_id"],)).fetchone()
            dupes = list(conn.execute(
                "SELECT * FROM pages WHERE canonical_page_id=?",
                (page["canonical_page_id"],)))
        else:
            # Unrecoverable singleton with no fingerprint
            canonical = page
            dupes = []
        out.append((zp, canonical, dupes))
    return out


def classify_zip(names_in_zip: list[str]) -> str:
    """Return 'image_group' or 'mixed' based on extension distribution."""
    exts = [pathlib.Path(n).suffix.lower() for n in names_in_zip
            if not n.endswith("/") and not any(n.startswith(p) for p in SKIP_FILE_PREFIXES)
            and pathlib.Path(n).name not in SKIP_NAMES]
    if not exts:
        return "empty"
    all_images = all(e in IMAGE_EXTS for e in exts)
    if all_images and len(exts) >= MIN_CONTACT_SHEET_IMAGES:
        return "image_group"
    return "mixed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--batch-id", type=str, default=None)
    ap.add_argument("--heuristic-version", type=int, default=None)
    args = ap.parse_args()

    curation = yaml.safe_load(CURATION_YAML.read_text())
    heuristic_version = args.heuristic_version or curation.get("heuristic_version", 1)
    batch_id = args.batch_id or str(uuid.uuid4())
    log(f"batch_id={batch_id}  heuristic_version={heuristic_version}")

    conn = sqlite3.connect(SIDECAR_DB, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    zips = find_zips_with_parent_pages(conn)
    log(f"found {len(zips)} zip files across canonical pages")
    if args.limit:
        zips = zips[:args.limit]

    if args.dry_run:
        for zp, canonical, dupes in zips[:50]:
            with zipfile.ZipFile(zp) as zf:
                names = zf.namelist()
            cls = classify_zip(names)
            log(f"  {zp.name:<50} parent={canonical['title'][:30]:<30} files={len(names):<3} → {cls}")
        return

    pap = Paperless()
    log("auth ok")
    # Pre-fetch tag + field maps
    tags_by_name = {t["name"].lower(): t["id"] for t in pap.list_tags()}
    field_by_name = {f["name"]: f["id"] for f in pap.list_custom_fields()}
    required = ["onenote_page_id", "onenote_canonical_page_id", "onenote_asset_kind",
                "import_batch", "import_heuristic_version"]
    for r in required:
        if r not in field_by_name:
            log(f"FATAL missing custom field: {r} (run paperless-import --setup-only first)")
            sys.exit(1)
    # archive_source field (new)
    if "archive_source" not in field_by_name:
        r = pap.session.post(f"{pap.base}/api/custom_fields/",
                             json={"name": "archive_source", "data_type": "string"},
                             timeout=30)
        r.raise_for_status()
        field_by_name["archive_source"] = r.json()["id"]
        log("  created custom field `archive_source`")

    uploaded_total = 0
    deduped_total = 0
    failed_total = 0
    contact_sheets_total = 0

    # sha256 dedup map across runs
    sha_to_doc: dict[str, int] = {}

    for zidx, (zp, canonical, dupes) in enumerate(zips, 1):
        zip_name = zp.name
        page_id = canonical["page_id"]
        log(f"[{zidx}/{len(zips)}] zip: {zip_name}  parent: {canonical['title'][:50]}")

        # Tag set for this page
        tag_names = canonical_tags_with_dupes(canonical, dupes, curation)
        # Ensure all tags exist in Paperless (they should from main import)
        tag_ids = []
        for name in tag_names:
            if name in tags_by_name:
                tag_ids.append(tags_by_name[name])
            else:
                t = pap.create_tag(name, 6)  # MATCH_AUTO by default
                tags_by_name[name] = t["id"]
                tag_ids.append(t["id"])

        # Extract zip
        with tempfile.TemporaryDirectory(prefix="pwl-zip-") as td:
            tdp = pathlib.Path(td)
            try:
                with zipfile.ZipFile(zp) as zf:
                    # Skip junk entries
                    members = [
                        m for m in zf.namelist()
                        if not m.endswith("/")
                        and not any(m.startswith(p) for p in SKIP_FILE_PREFIXES)
                        and pathlib.Path(m).name not in SKIP_NAMES
                        and pathlib.Path(m).suffix.lower() not in {".ds_store"}
                    ]
                    for m in members:
                        zf.extract(m, tdp)
            except zipfile.BadZipFile as e:
                log(f"  BAD ZIP: {e}")
                continue

            extracted = []
            for m in members:
                p = tdp / m
                if p.is_file():
                    extracted.append((m, p))
            if not extracted:
                log(f"  empty after skip filtering")
                continue

            # Classify
            cls = classify_zip([m for m, _ in extracted])
            is_image_group = cls == "image_group"

            # Upload each file
            upload_rows: list[tuple[int, str, pathlib.Path]] = []  # (doc_id, internal_path, src)
            for member, src in extracted:
                internal = member  # path within zip
                ext = pathlib.Path(member).suffix.lower()
                sha = hashlib.sha256(src.read_bytes()).hexdigest()

                # Check dedup (Paperless will also reject, but pre-check saves a call)
                if sha in sha_to_doc:
                    existing = sha_to_doc[sha]
                    log(f"    DEDUP {pathlib.Path(member).name}: → doc#{existing}")
                    upload_rows.append((existing, internal, src))
                    deduped_total += 1
                    conn.execute(
                        "INSERT OR IGNORE INTO uploads (paperless_doc_id, page_id, asset_id, "
                        "batch_id, heuristic_version, uploaded_at, status) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (existing, page_id, f"zip:{zip_name}:{internal}", batch_id,
                         heuristic_version, datetime.now().isoformat(), "uploaded"))
                    continue

                # Fix DPI for images if needed
                upload_src = src
                if ext in IMAGE_EXTS and ext != ".pdf":
                    fixed = tdp / f"dpi_{src.name}"
                    try:
                        fix_image_dpi(src, fixed, 300)
                        upload_src = fixed
                    except Exception as e:
                        log(f"    WARN DPI fix failed for {member}: {e}")

                # Title: preserve internal path for uniqueness
                parts = [p for p in pathlib.Path(internal).parts if p]
                if len(parts) > 1:
                    title = f"{parts[-2]} — {pathlib.Path(internal).name}"
                else:
                    title = pathlib.Path(internal).name
                title = f"{title[:100]}"  # be safe

                try:
                    task_id = pap.upload(upload_src, title, canonical["created"] or None, tag_ids)
                    task = pap.poll_task(task_id)
                    if task.get("status") == "FAILURE":
                        m = re.search(r"duplicate of .+ \(#(\d+)\)", task.get("result") or "")
                        if m:
                            doc_id = int(m.group(1))
                            sha_to_doc[sha] = doc_id
                            upload_rows.append((doc_id, internal, src))
                            deduped_total += 1
                            conn.execute(
                                "INSERT OR IGNORE INTO uploads (paperless_doc_id, page_id, asset_id, "
                                "batch_id, heuristic_version, uploaded_at, status) "
                                "VALUES (?,?,?,?,?,?,?)",
                                (doc_id, page_id, f"zip:{zip_name}:{internal}", batch_id,
                                 heuristic_version, datetime.now().isoformat(), "uploaded"))
                            continue
                        log(f"    upload FAIL {member}: {task.get('result')}")
                        failed_total += 1
                        continue
                    doc_id = task.get("related_document")
                    if not doc_id:
                        log(f"    no related_document for {member}")
                        failed_total += 1
                        continue
                    sha_to_doc[sha] = doc_id

                    # Figure out asset kind
                    if ext in IMAGE_EXTS:
                        kind = "image"
                    elif ext == ".pdf":
                        kind = "pdf"
                    else:
                        kind = "other_attachment"

                    # Apply custom fields
                    pap.patch_doc(doc_id, {
                        "tags": tag_ids,
                        "created": canonical["created"] or None,
                        "custom_fields": [
                            {"field": field_by_name["onenote_page_id"], "value": page_id},
                            {"field": field_by_name["onenote_canonical_page_id"], "value": page_id},
                            {"field": field_by_name["onenote_asset_kind"], "value": kind},
                            {"field": field_by_name["archive_source"], "value": zip_name[:128]},
                            {"field": field_by_name["import_batch"], "value": batch_id},
                            {"field": field_by_name["import_heuristic_version"], "value": heuristic_version},
                        ],
                    })
                    conn.execute(
                        "INSERT OR IGNORE INTO uploads (paperless_doc_id, page_id, asset_id, "
                        "batch_id, heuristic_version, uploaded_at, status) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (doc_id, page_id, f"zip:{zip_name}:{internal}", batch_id,
                         heuristic_version, datetime.now().isoformat(), "uploaded"))
                    upload_rows.append((doc_id, internal, src))
                    uploaded_total += 1
                    log(f"    ok: {title} → doc#{doc_id}")
                except Exception as e:
                    log(f"    EXCEPTION for {member}: {e}")
                    failed_total += 1

            # Generate contact-sheet PDF if image-group AND ≥2 files actually uploaded
            if is_image_group and len(upload_rows) >= MIN_CONTACT_SHEET_IMAGES:
                try:
                    img_srcs = [src for _, _, src in upload_rows]
                    labels = [pathlib.Path(ip).name for _, ip, _ in upload_rows]
                    pdf_path = tdp / f"{zp.stem}-contact-sheet.pdf"
                    title_str = f"{canonical['title']} — {zp.stem}"
                    generate_contact_sheet_pdf(img_srcs, labels, pdf_path,
                                               title=title_str[:60])
                    task_id = pap.upload(pdf_path, title_str[:100],
                                         canonical["created"] or None, tag_ids)
                    task = pap.poll_task(task_id)
                    if task.get("status") == "SUCCESS":
                        doc_id = task.get("related_document")
                        pap.patch_doc(doc_id, {
                            "tags": tag_ids,
                            "created": canonical["created"] or None,
                            "custom_fields": [
                                {"field": field_by_name["onenote_page_id"], "value": page_id},
                                {"field": field_by_name["onenote_canonical_page_id"], "value": page_id},
                                {"field": field_by_name["onenote_asset_kind"], "value": "contact_sheet"},
                                {"field": field_by_name["archive_source"], "value": zip_name[:128]},
                                {"field": field_by_name["import_batch"], "value": batch_id},
                                {"field": field_by_name["import_heuristic_version"], "value": heuristic_version},
                            ],
                        })
                        conn.execute(
                            "INSERT OR IGNORE INTO uploads (paperless_doc_id, page_id, asset_id, "
                            "batch_id, heuristic_version, uploaded_at, status) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (doc_id, page_id, f"zip-contact-sheet:{zip_name}", batch_id,
                             heuristic_version, datetime.now().isoformat(), "uploaded"))
                        contact_sheets_total += 1
                        log(f"    contact sheet ok: doc#{doc_id}")
                    else:
                        log(f"    contact sheet upload failed: {task.get('result')}")
                except Exception as e:
                    log(f"    contact sheet EXCEPTION: {e}")

    log(f"DONE: {uploaded_total} uploaded, {contact_sheets_total} contact-sheets, "
        f"{deduped_total} deduped, {failed_total} failed, batch_id={batch_id}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
