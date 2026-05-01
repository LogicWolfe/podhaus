"""Paperless Wipe — reverse imports by soft-deleting uploaded Paperless docs.

CLI:
  --batch UUID             wipe all docs from this batch
  --all-onenote            wipe every doc with an import_batch value (all-time)
  --heuristic-version N    wipe docs with this heuristic_version
  --dry-run                show what would be wiped
  --yes                    skip confirmation prompt

Uses the Paperless bulk-edit API to soft-delete (recoverable in Trash for
30 days). Updates the sidecar's `uploads` table status from 'uploaded' to
'wiped' so re-runs of paperless-import don't re-skip wiped docs.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
import time
from datetime import datetime

import requests

SIDECAR_DB = pathlib.Path("/state/paperless-imports.sqlite")
PAPERLESS_URL = os.environ["PAPERLESS_URL"].rstrip("/")
PAPERLESS_USERNAME = os.environ["PAPERLESS_USERNAME"]
PAPERLESS_PASSWORD = os.environ["PAPERLESS_PASSWORD"]
PAPERLESS_HOST_HEADER = os.environ.get("PAPERLESS_HOST_HEADER", "paperless.pod.haus")


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


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--batch", type=str)
    g.add_argument("--all-onenote", action="store_true")
    g.add_argument("--heuristic-version", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(SIDECAR_DB, isolation_level=None)
    conn.row_factory = sqlite3.Row

    if args.batch:
        rows = list(conn.execute(
            "SELECT * FROM uploads WHERE batch_id=? AND status='uploaded'",
            (args.batch,),
        ))
        label = f"batch {args.batch}"
    elif args.all_onenote:
        rows = list(conn.execute("SELECT * FROM uploads WHERE status='uploaded'"))
        label = "ALL onenote imports"
    elif args.heuristic_version is not None:
        rows = list(conn.execute(
            "SELECT * FROM uploads WHERE heuristic_version=? AND status='uploaded'",
            (args.heuristic_version,),
        ))
        label = f"heuristic_version={args.heuristic_version}"
    else:
        log("no filter given")
        sys.exit(1)

    doc_ids = [r["paperless_doc_id"] for r in rows if r["paperless_doc_id"]]
    log(f"wipe target: {label}")
    log(f"  {len(doc_ids)} Paperless documents to soft-delete")

    if not doc_ids:
        log("nothing to do")
        return

    if args.dry_run:
        for r in rows[:20]:
            log(f"  - doc_id={r['paperless_doc_id']} page={r['page_id'][:16]}... asset={r['asset_id']}")
        if len(rows) > 20:
            log(f"  ... +{len(rows)-20} more")
        return

    if not args.yes:
        print(f"\nAbout to soft-delete {len(doc_ids)} Paperless documents. Type 'wipe' to confirm: ",
              end="", flush=True)
        ans = sys.stdin.readline().strip()
        if ans != "wipe":
            log("aborted")
            return

    s = auth_session()
    # Bulk-edit API — set_permissions/delete
    CHUNK = 100
    for i in range(0, len(doc_ids), CHUNK):
        batch_ids = doc_ids[i:i+CHUNK]
        log(f"  soft-deleting docs {i+1}..{i+len(batch_ids)}")
        r = s.post(
            f"{PAPERLESS_URL}/api/documents/bulk_edit/",
            json={"documents": batch_ids, "method": "delete"},
            timeout=60,
        )
        if not r.ok:
            log(f"    bulk_edit failed {r.status_code}: {r.text[:400]}")
            r.raise_for_status()
        time.sleep(1)

    # Mark sidecar rows wiped
    for r in rows:
        conn.execute(
            "UPDATE uploads SET status='wiped' WHERE paperless_doc_id=?",
            (r["paperless_doc_id"],),
        )
    log(f"DONE: {len(doc_ids)} documents soft-deleted (recoverable in Paperless Trash for 30 days)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
