#!/usr/bin/env python3
"""Prove the storage mount and a responding engine within Docker's timeout."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("flood-publish.py"))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

sentinel = Path(sys.argv[1])
if len(sys.argv) == 3:
    assert sentinel.read_text().strip() == sys.argv[2], "Media volume identity differs"
else:
    assert sentinel.is_file(), "Media mount sentinel is missing"
assert Path('/flood-db').is_mount(), "Session directory is not mounted"
assert publisher.rpc("system.client_version"), "Engine returned no version"
