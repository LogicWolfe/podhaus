#!/usr/bin/env python3
"""Publish the shared address catalog as Komodo variables; --verify detects drift."""

import argparse
import json
from dataclasses import dataclass, fields
from ipaddress import IPv4Address
from pathlib import Path


@dataclass(frozen=True)
class LanAddresses:
    bilby_ipv4: str
    bandicoot_ipv4: str
    kangaroo_ipv4: str
    kangaroo_1g_ipv4: str
    fractal_windows_ipv4: str
    turn_touch_burrow_ipv4: str
    led_strip_grasshopper_ipv4: str
    pizero_ipv4: str
    nb_macbook_air_ipv4: str

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, str):
                raise ValueError(f"{field.name} must be an IPv4 address string")
            IPv4Address(value)

    @classmethod
    def read(cls, path: Path) -> "LanAddresses":
        return cls(**json.loads(path.read_text()))

    def komodo_toml(self) -> str:
        entries = [
            "# Generated from config/lan-addresses.json by tools/render-lan-addresses.py.\n"
        ]
        for field in fields(self):
            entries.append(
                f'[[variable]]\nname = "LAN_{field.name.upper()}"\n'
                f'value = "{getattr(self, field.name)}"\n'
                'description = "Shared LAN address from config/lan-addresses.json"\n'
            )
        return "\n".join(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rendered = LanAddresses.read(root / "config/lan-addresses.json").komodo_toml()
    destination = root / "komodo/sync/lan-addresses.toml"
    if args.verify:
        if destination.read_text() != rendered:
            raise SystemExit(
                "LAN address variables are stale; run tools/render-lan-addresses.py"
            )
        print("LAN address variables: verified")
    else:
        destination.write_text(rendered)
        print("LAN address variables: rendered")


if __name__ == "__main__":
    main()
