"""Paperless crosslink — set the `related_docs` (document_link) custom field
on every doc sharing an `onenote_canonical_page_id`, so Paperless renders
them as linked siblings in the doc detail UI.

Runs after the main import / after zip extraction. Idempotent — safe to
rerun. Priority for the "primary" doc (the one whose related_docs field
we set, Paperless auto-populates reverse links on the rest):

  md_body > pdf > other_attachment > image > contact_sheet

Env: PAPERLESS_URL, PAPERLESS_USERNAME, PAPERLESS_PASSWORD, PAPERLESS_HOST_HEADER.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

import requests

SIDECAR_DB = pathlib.Path("/state/paperless-imports.sqlite")

PAPERLESS_URL = os.environ["PAPERLESS_URL"].rstrip("/")
PAPERLESS_USERNAME = os.environ["PAPERLESS_USERNAME"]
PAPERLESS_PASSWORD = os.environ["PAPERLESS_PASSWORD"]
PAPERLESS_HOST_HEADER = os.environ.get("PAPERLESS_HOST_HEADER", "paperless.pod.haus")

PRIORITY = {"md_body": 0, "pdf": 1, "other_attachment": 2, "image": 3, "contact_sheet": 4}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def auth_session() -> requests.Session:
    s = requests.Session()
    s.headers["Host"] = PAPERLESS_HOST_HEADER
    s.headers["Accept"] = "application/json; version=5"
    r = s.post(
        f"{PAPERLESS_URL}/api/token/",
        data={"username": PAPERLESS_USERNAME, "password": PAPERLESS_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    s.headers["Authorization"] = f"Token {r.json()['token']}"
    return s


def ensure_document_link_field(s: requests.Session) -> int:
    r = s.get(f"{PAPERLESS_URL}/api/custom_fields/?page_size=100", timeout=30)
    r.raise_for_status()
    for f in r.json()["results"]:
        if f["name"] == "related_docs":
            return f["id"]
    r = s.post(
        f"{PAPERLESS_URL}/api/custom_fields/",
        json={"name": "related_docs", "data_type": "documentlink"},
        timeout=30,
    )
    if not r.ok:
        log(f"create documentlink field failed {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
    log("  created custom field `related_docs` (documentlink)")
    return r.json()["id"]


def get_field_id(s: requests.Session, name: str) -> int | None:
    r = s.get(f"{PAPERLESS_URL}/api/custom_fields/?page_size=100", timeout=30)
    r.raise_for_status()
    for f in r.json()["results"]:
        if f["name"] == name:
            return f["id"]
    return None


def fetch_all_docs(s: requests.Session, canonical_field_id: int) -> list[dict]:
    """Pull every doc that has the onenote_canonical_page_id custom field set."""
    out: list[dict] = []
    # Paperless custom field filter syntax: custom_fields__id_exact
    url = f"{PAPERLESS_URL}/api/documents/?custom_fields__field_id={canonical_field_id}&page_size=200"
    while url:
        r = s.get(url, timeout=60)
        r.raise_for_status()
        j = r.json()
        out.extend(j["results"])
        url = j.get("next")
    return out


def cf_value(doc: dict, field_id: int) -> str | None:
    for cf in doc.get("custom_fields") or []:
        if cf.get("field") == field_id:
            return cf.get("value")
    return None


def main() -> None:
    s = auth_session()
    log(f"auth ok: {PAPERLESS_URL}")

    canonical_field_id = get_field_id(s, "onenote_canonical_page_id")
    kind_field_id = get_field_id(s, "onenote_asset_kind")
    if not canonical_field_id or not kind_field_id:
        log("required custom fields missing; run paperless-import --setup-only first")
        sys.exit(1)

    related_field_id = ensure_document_link_field(s)

    log("fetching all docs (paginated via explicit page numbers; Paperless's")
    log("  `next` URL points at the public CF-protected hostname and would 403)")
    docs: list[dict] = []
    page = 1
    page_size = 200
    while True:
        r = s.get(
            f"{PAPERLESS_URL}/api/documents/",
            params={"page_size": page_size, "page": page, "ordering": "id"},
            timeout=60,
        )
        r.raise_for_status()
        j = r.json()
        results = j.get("results") or []
        docs.extend(results)
        if len(results) < page_size:
            break
        page += 1
    doc_by_id = {d["id"]: d for d in docs}
    log(f"  {len(docs)} total docs in Paperless")

    # Grouping via the sidecar — authoritative page→doc mapping, captures the
    # sha256-dedup links where one Paperless doc serves multiple OneNote pages
    # (which the stored onenote_canonical_page_id field alone misses).
    log("grouping via sidecar uploads table")
    conn = sqlite3.connect(f"file:{SIDECAR_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # For each canonical OneNote page, find pages in its group (canonical + dupes)
    canonical_to_pageids: dict[str, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT page_id, canonical_page_id, is_canonical FROM pages"):
        if r["is_canonical"]:
            canonical_to_pageids[r["page_id"]].add(r["page_id"])
        elif r["canonical_page_id"]:
            canonical_to_pageids[r["canonical_page_id"]].add(r["page_id"])

    # Find all uploads rows; map page_id -> [doc_ids]
    page_to_docids: dict[str, set[int]] = defaultdict(set)
    for r in conn.execute(
        "SELECT page_id, paperless_doc_id FROM uploads WHERE status='uploaded'"
    ):
        page_to_docids[r["page_id"]].add(r["paperless_doc_id"])
    conn.close()

    # Build groups: canonical page → set of doc_ids (union of all uploads
    # linked to any page in the canonical's group, including sha-dedup links)
    groups: dict[str, list[dict]] = defaultdict(list)
    for canonical, pageids in canonical_to_pageids.items():
        docids: set[int] = set()
        for pid in pageids:
            docids |= page_to_docids.get(pid, set())
        # Dereference to actual doc objects we fetched
        members = [doc_by_id[did] for did in docids if did in doc_by_id]
        if members:
            groups[canonical] = members
    log(f"  {len(groups)} distinct canonical page groups (sidecar-derived)")

    linked_groups = 0
    linked_edges = 0
    skipped_singletons = 0
    for cp, members in groups.items():
        if len(members) < 2:
            skipped_singletons += 1
            continue
        # Pick primary by kind priority
        def sort_key(d: dict) -> tuple[int, int]:
            k = cf_value(d, kind_field_id) or ""
            return (PRIORITY.get(k, 99), d["id"])
        members.sort(key=sort_key)
        primary = members[0]
        siblings = [m["id"] for m in members[1:]]

        # Check if already linked — skip if related_docs already matches
        existing_val = cf_value(primary, related_field_id)
        try:
            existing_ids = set(existing_val) if isinstance(existing_val, list) else set()
        except Exception:
            existing_ids = set()
        if existing_ids == set(siblings):
            linked_groups += 1
            continue

        # Merge related_docs into the existing custom_fields list — a PATCH
        # on custom_fields in Paperless REPLACES the whole list, so we must
        # preserve the onenote_page_id/batch/etc fields already set.
        merged_cf: list[dict] = []
        already_has_related = False
        for cf in primary.get("custom_fields") or []:
            if cf.get("field") == related_field_id:
                merged_cf.append({"field": related_field_id, "value": siblings})
                already_has_related = True
            else:
                merged_cf.append({"field": cf["field"], "value": cf.get("value")})
        if not already_has_related:
            merged_cf.append({"field": related_field_id, "value": siblings})
        body = {"custom_fields": merged_cf}
        r = s.patch(f"{PAPERLESS_URL}/api/documents/{primary['id']}/",
                    json=body, timeout=30)
        if not r.ok:
            log(f"  WARN PATCH doc#{primary['id']} failed {r.status_code}: {r.text[:200]}")
            continue
        linked_groups += 1
        linked_edges += len(siblings)

    log(f"DONE: {linked_groups} groups linked, {linked_edges} sibling edges, "
        f"{skipped_singletons} singletons skipped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
