#!/usr/bin/env python3
"""Merge enforced Plex preferences into the live Preferences.xml.

Usage: plex-preferences.py <template> <target>

If <target> exists, enforced attributes from <template> are overlaid
onto it — all other attributes are preserved. If <target> doesn't
exist (first boot), the template is written as the initial file.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def parse_preferences(path: Path) -> dict[str, str]:
    """Parse a Preferences.xml into a dict of attr name → value."""
    tree = ET.parse(path)
    return dict(tree.getroot().attrib)

def write_preferences(attrs: dict[str, str], path: Path) -> None:
    """Write attrs as a single-element Preferences.xml."""
    root = ET.Element("Preferences")
    for k, v in sorted(attrs.items()):
        root.set(k, v)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    # Plex expects a trailing newline
    with open(path, "a") as f:
        f.write("\n")

def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <template> <target>", file=sys.stderr)
        sys.exit(1)

    template_path = Path(sys.argv[1])
    target_path = Path(sys.argv[2])

    enforced = parse_preferences(template_path)

    if target_path.exists():
        # Merge: overlay enforced attrs onto existing file
        existing = parse_preferences(target_path)
        merged = {**existing, **enforced}
        changed = {k: v for k, v in enforced.items() if existing.get(k) != v}
        if changed:
            for k, v in sorted(changed.items()):
                old = existing.get(k, "(missing)")
                # Redact tokens in log output
                if "token" in k.lower():
                    old = old[:8] + "..." if len(old) > 8 else old
                    v = v[:8] + "..." if len(v) > 8 else v
                print(f"  {k}: {old} → {v}")
            write_preferences(merged, target_path)
            print(f"  merged {len(changed)} enforced attr(s) into {target_path}")
        else:
            print(f"  all enforced attrs already match in {target_path}")
    else:
        # First boot: seed from template
        write_preferences(enforced, target_path)
        print(f"  seeded {target_path} with {len(enforced)} attrs (first boot)")

if __name__ == "__main__":
    main()
