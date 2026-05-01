"""Paperless diff-plan generator — builds a human-readable report of which
tags each canonical page will get under the current curation plan, and who
gets no tags at all.

Reads:
  ~/repos/podhaus-migration-state/paperless-imports.sqlite
  ~/repos/podhaus-migration-state/paperless-curation.yaml
Writes:
  ~/repos/podhaus-migration-state/paperless-diff-plan.md

Runs on host (no Paperless API, no container). Applies curation rules
against canonical pages only (dupes merge up into their canonical).

Tag application sources tracked per (page, tag) pair so the report can
highlight regex-only additions (the "insufficiently specific regex"
review risk).
"""
from __future__ import annotations

import pathlib
import re
import sqlite3
import sys
from collections import defaultdict
from typing import Any

import yaml

SIDECAR_DB = pathlib.Path("~/repos/podhaus-migration-state/paperless-imports.sqlite").expanduser()
CURATION_YAML = pathlib.Path("~/repos/podhaus-migration-state/paperless-curation.yaml").expanduser()
OUT_MD = pathlib.Path("~/repos/podhaus-migration-state/paperless-diff-plan.md").expanduser()


def lower_tag(t: str) -> str:
    """Apply the global lowercase + hyphenate-multi-word rules."""
    t = t.lower().strip()
    t = re.sub(r"\s+", "-", t)
    return t


def load_curation() -> dict:
    with CURATION_YAML.open("r") as f:
        return yaml.safe_load(f)


def section_dropped_by_global(section: str | None, curation: dict) -> bool:
    if not section:
        return False
    for gr in curation.get("global_rules", []) or []:
        if gr.get("action") != "drop":
            continue
        m = gr.get("match") or {}
        if m.get("kind") == "section_regex":
            if re.match(m["pattern"], section):
                return True
        elif m.get("kind") == "section_literal":
            if section == m["value"]:
                return True
    return False


def compute_page_tags(page: sqlite3.Row, curation: dict) -> dict[str, set[str]]:
    """Return {tag -> set of source labels} for a canonical page."""
    tags: dict[str, set[str]] = defaultdict(set)
    notebook = page["notebook"]
    section = page["section"]
    title = page["title"] or ""
    page_id = page["page_id"]

    # --- Notebook tag ---
    nb_rule = (curation.get("notebook_tags") or {}).get(notebook) or {"action": "keep"}
    nb_action = nb_rule.get("action", "keep")
    if nb_action == "keep":
        nb_tag = lower_tag(nb_rule.get("rename_to") or notebook)
        tags[nb_tag].add(f"notebook:{notebook}")
    elif nb_action == "rename":
        nb_tag = lower_tag(nb_rule.get("rename_to"))
        tags[nb_tag].add(f"notebook:{notebook}→rename")
    # action=drop → no notebook tag
    for t in nb_rule.get("also_apply") or []:
        tags[lower_tag(t)].add(f"notebook:{notebook}:also_apply")

    # --- Section tag ---
    sec_key = f"{notebook}/{section}" if section else None
    sec_rule = (curation.get("section_tags") or {}).get(sec_key) if sec_key else None
    sec_dropped_global = section_dropped_by_global(section, curation)

    if section and not sec_dropped_global:
        if sec_rule:
            sec_action = sec_rule.get("action", "keep")
            if sec_action == "keep":
                sec_tag = lower_tag(sec_rule.get("rename_to") or section)
                tags[sec_tag].add(f"section:{sec_key}")
            elif sec_action == "rename":
                sec_tag = lower_tag(sec_rule.get("rename_to"))
                tags[sec_tag].add(f"section:{sec_key}→{sec_tag}")
            # action=drop → no section tag
            for t in sec_rule.get("also_apply") or []:
                tags[lower_tag(t)].add(f"section:{sec_key}:also_apply")
        else:
            # Default: keep section name lowercased
            tags[lower_tag(section)].add(f"section:{sec_key}:default")

    # --- Per-page overrides ---
    for ovr in curation.get("per_page_overrides") or []:
        if ovr.get("page_id") == page_id:
            for t in ovr.get("add_tags") or []:
                tags[lower_tag(t)].add("per-page-override")
            for t in ovr.get("remove_tags") or []:
                tags.pop(lower_tag(t), None)

    # --- Content tag seed_pages (explicit per-page listing under a content tag) ---
    # Match by page_id first, else by title substring.
    for tag_name, tag_def in (curation.get("content_tags") or {}).items():
        for sp in tag_def.get("seed_pages") or []:
            matched = False
            if sp.get("page_id") and sp["page_id"] == page_id:
                matched = True
            elif sp.get("title"):
                t = sp["title"]
                if t == title or (t in title) or (title in t):
                    matched = True
            if matched:
                tags[lower_tag(tag_name)].add(f"seed_pages:{tag_name}")
                for extra in sp.get("add_tags") or []:
                    tags[lower_tag(extra)].add(f"seed_pages:{tag_name}:add_tags")

    # --- Content tag title-regex ---
    for tag_name, tag_def in (curation.get("content_tags") or {}).items():
        pattern = tag_def.get("title_seed_pattern")
        if not pattern:
            continue
        # Excludes are case-insensitive substrings; if any appears in the
        # title, the regex is suppressed for this tag.
        excludes = tag_def.get("title_seed_exclude") or []
        title_lc = title.lower()
        if any(ex.lower() in title_lc for ex in excludes):
            continue
        try:
            if re.search(pattern, title):
                tags[lower_tag(tag_name)].add(f"regex:{tag_name}")
        except re.error as e:
            print(f"WARN bad regex for {tag_name}: {e}", file=sys.stderr)

    return dict(tags)


def classify_source(sources: set[str]) -> str:
    """Simplified to 2 categories:
    - explicit: page has at least one explicit source (section/notebook/
      per-page/dupe-merge); regex may or may not also match — doesn't matter
      because the tag is locked in by the explicit rule.
    - regex-only: page got this tag ONLY via a content-tag regex match.
      Review target for false positives.
    """
    has_explicit = any(not s.startswith("regex:") for s in sources)
    return "explicit" if has_explicit else "regex-only"


def main() -> None:
    curation = load_curation()
    conn = sqlite3.connect(SIDECAR_DB)
    conn.row_factory = sqlite3.Row

    pages = list(conn.execute("SELECT * FROM pages WHERE is_canonical=1"))
    # Load dupes grouped by canonical_page_id so we can merge their
    # section/notebook-derived tags upward.
    dupes_by_canonical: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for dupe in conn.execute("SELECT * FROM pages WHERE canonical_page_id IS NOT NULL"):
        dupes_by_canonical[dupe["canonical_page_id"]].append(dupe)
    conn.close()

    page_tags: dict[str, tuple[sqlite3.Row, dict[str, set[str]]]] = {}
    for p in pages:
        tags = compute_page_tags(p, curation)
        # --- Merge dupe-contributed tags upward into canonical ---
        # Each dupe's section/notebook rules contribute to the canonical's
        # tag set (per the migration doc's dedup plan). Regex matches on
        # dupe titles are NOT merged (regex is applied to the canonical's
        # own title in the compute_page_tags above).
        for dupe in dupes_by_canonical.get(p["page_id"], []):
            dupe_tags = compute_page_tags(dupe, curation)
            for tag, sources in dupe_tags.items():
                # Skip regex-match sources (those belong to the dupe's title,
                # which the canonical doesn't have). Only propagate section/
                # notebook/per-page-override sources from the dupe.
                non_regex_sources = {s for s in sources if not s.startswith("regex:")}
                if non_regex_sources:
                    dupe_section = f"{dupe['notebook']}/{dupe['section'] or '(none)'}"
                    for s in non_regex_sources:
                        tags.setdefault(tag, set()).add(f"dupe-merge:{dupe_section}:{s}")
        # --- Apply tag_exclusions ---
        # Rules remove prefix-matching tags when another prefix-matching tag
        # is present, UNLESS the removed tag came from a per-page-override
        # (explicit > rule).
        for rule in curation.get("tag_exclusions") or []:
            has_prefixes = rule.get("if_has_any_with_prefix") or []
            remove_prefixes = rule.get("remove_any_with_prefix") or []
            has_match = any(
                any(t.startswith(pref) for pref in has_prefixes)
                for t in tags
            )
            if not has_match:
                continue
            to_remove = [
                t for t in tags
                if any(t.startswith(pref) for pref in remove_prefixes)
                and "per-page-override" not in tags[t]
            ]
            for t in to_remove:
                del tags[t]
        # Fallback: apply `unknown` to any page with zero user-facing tags.
        if not tags and "unknown" in (curation.get("content_tags") or {}):
            tags["unknown"] = {"fallback:no-other-tags"}
        page_tags[p["page_id"]] = (p, tags)

    # --- Aggregate: tag → list of (page, sources) ---
    tag_to_pages: dict[str, list[tuple[sqlite3.Row, set[str]]]] = defaultdict(list)
    # Also build page_id → all-tag-names lookup for the "full tag list" shown
    # next to each page entry.
    page_all_tags: dict[str, list[str]] = {}
    for pid, (p, tags) in page_tags.items():
        tag_names = sorted(tags.keys())
        page_all_tags[pid] = tag_names
        for tag, sources in tags.items():
            tag_to_pages[tag].append((p, sources))

    # --- Untagged pages ---
    untagged = [(p, t) for pid, (p, t) in page_tags.items() if not t]

    # --- Emit markdown ---
    lines: list[str] = []
    lines.append("# Paperless Tag Plan — Diff Preview\n")
    lines.append(
        "Generated from paperless-imports.sqlite + paperless-curation.yaml.\n"
        "Canonical pages only. Pages grouped by final tag, with source annotation.\n"
    )
    lines.append(f"**Total canonical pages:** {len(page_tags)}  ")
    lines.append(f"**Distinct tags:** {len(tag_to_pages)}  ")
    lines.append(f"**Untagged pages:** {len(untagged)}\n")
    lines.append("---\n")

    # Global default: all tags MATCH_AUTO unless explicitly NONE in
    # content_tags. Paperless classifier trains on AUTO tags and auto-applies
    # to new docs; user corrects wrong predictions, classifier improves.
    # MATCH_NONE is the exception (only for system fallback / metadata tags).
    explicit_none_tags = {
        name.lower()
        for name, tdef in (curation.get("content_tags") or {}).items()
        if (tdef or {}).get("matching_algorithm") == "none"
    }
    def is_auto(tag: str) -> bool:
        return tag.lower() not in explicit_none_tags

    # Sort tags by pages desc, then by name
    for tag, page_list in sorted(tag_to_pages.items(), key=lambda x: (-len(x[1]), x[0])):
        badge = "" if is_auto(tag) else " **[noauto]**"
        lines.append(f"## `{tag}`{badge} — {len(page_list)} pages\n")

        # Bucket within tag by source category
        by_source: dict[str, list[tuple[sqlite3.Row, set[str]]]] = defaultdict(list)
        for pg, srcs in page_list:
            by_source[classify_source(srcs)].append((pg, srcs))

        for label in ("explicit", "regex-only"):
            if label not in by_source:
                continue
            lines.append(f"### {label} ({len(by_source[label])})\n")
            sorted_pages = sorted(by_source[label], key=lambda x: (x[0]["title"] or "").lower())
            # De-dupe pages: a page might appear here multiple times if it
            # matched the same tag via multiple sources; collapse to one line.
            seen_page_ids = set()
            for pg, _srcs in sorted_pages:
                if pg["page_id"] in seen_page_ids:
                    continue
                seen_page_ids.add(pg["page_id"])
                title = (pg["title"] or "(untitled)").replace("\n", " ")
                all_tags = page_all_tags[pg["page_id"]]
                tag_list = ", ".join(all_tags)
                lines.append(f"- {title}  `({tag_list})`")
            lines.append("")

    if untagged:
        lines.append("---\n")
        lines.append(f"## Untagged pages ({len(untagged)})\n")
        lines.append(
            "These canonical pages get NO tags under current rules — "
            "they'll land in Paperless with only the import system tags "
            "(`import:onenote`, `import:batch-*`). Consider whether they need "
            "explicit per-page overrides.\n"
        )
        for pg, _ in sorted(untagged, key=lambda x: (x[0]["title"] or "").lower()):
            title = (pg["title"] or "(untitled)").replace("\n", " ")
            origin = f"{pg['notebook']}/{pg['section'] or '(no section)'}"
            lines.append(f"- {title}  _({origin})_")

    OUT_MD.write_text("\n".join(lines))
    print(f"wrote {OUT_MD}  ({len(page_tags)} canonical pages, {len(tag_to_pages)} tags, {len(untagged)} untagged)")


if __name__ == "__main__":
    main()
