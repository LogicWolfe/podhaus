"""Unit tests for docs-source slot reconciliation."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "reconcile-docs-sources"
LOADER = importlib.machinery.SourceFileLoader("reconcile_docs_sources", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = MODULE
LOADER.exec_module(MODULE)


class FakeCommands:
    def __init__(self) -> None:
        self.mounts: set[Path] = set()
        self.bindings: dict[Path, os.stat_result] = {}
        self.calls: list[list[str]] = []

    def mounted(self, path: Path) -> bool:
        return path in self.mounts

    def run(self, args: list[str], *, check: bool = True):
        self.calls.append(args)
        if args[:2] == ["mount", "--bind"]:
            source, target = Path(args[-2]), Path(args[-1])
            self.mounts.add(target)
            self.bindings[target] = source.stat()
        elif args[0] == "umount":
            target = Path(args[-1])
            self.mounts.remove(target)
            self.bindings.pop(target)

    def same_object(self, left: Path, right: Path) -> bool:
        source_stat = left.stat()
        mounted_stat = self.bindings.get(right)
        return (
            mounted_stat is not None
            and mounted_stat.st_dev == source_stat.st_dev
            and mounted_stat.st_ino == source_stat.st_ino
        )


class SourceReconcilerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        MODULE.SLOT_ROOT = root / "slots"
        MODULE.STATE_ROOT = root / "state"
        self.source = root / "source"
        (self.source / ".git").mkdir(parents=True)
        self.slot = MODULE.SourceSlot("chezmoi", self.source, Path(".git"))
        self.commands = FakeCommands()
        self.reconciler = MODULE.SourceReconciler((self.slot,), self.commands)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prepare_creates_shared_root_and_unavailable_slot(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.reconciler.prepare()

        self.assertIn("SOURCE-ROOT-PREPARED", output.getvalue())
        self.assertIn("SOURCE-SLOT-CREATED chezmoi", output.getvalue())
        self.assertTrue((self.slot.slot / MODULE.UNAVAILABLE_MARKER).is_file())
        self.assertIn(["mount", "--make-rshared", str(MODULE.SLOT_ROOT)], self.commands.calls)

    def test_reconcile_mounts_and_withdraws_source(self) -> None:
        with redirect_stdout(StringIO()):
            self.reconciler.prepare()
            self.reconciler.reconcile()
        self.assertIn(self.slot.slot, self.commands.mounts)
        self.assertEqual(self.slot.state_file.read_text().strip(), str(self.source))

        (self.source / ".git").rmdir()
        with redirect_stdout(StringIO()):
            self.reconciler.reconcile()
        self.assertNotIn(self.slot.slot, self.commands.mounts)
        self.assertFalse(self.slot.state_file.exists())

    def test_reconcile_is_idempotent_when_source_mount_matches(self) -> None:
        with redirect_stdout(StringIO()):
            self.reconciler.prepare()
            self.reconciler.reconcile()
        first_calls = len(self.commands.calls)
        self.reconciler.reconcile()
        self.assertEqual(len(self.commands.calls), first_calls)

    def test_reconcile_remounts_source_replaced_at_same_path(self) -> None:
        with redirect_stdout(StringIO()):
            self.reconciler.prepare()
            self.reconciler.reconcile()
        original = self.source.with_name("original-source")
        self.source.rename(original)
        (self.source / ".git").mkdir(parents=True)
        first_calls = len(self.commands.calls)

        with redirect_stdout(StringIO()):
            self.reconciler.reconcile()

        self.assertGreater(len(self.commands.calls), first_calls)
        self.assertIn(["umount", str(self.slot.slot)], self.commands.calls[first_calls:])
        self.assertTrue(self.commands.same_object(self.source, self.slot.slot))


if __name__ == "__main__":
    unittest.main()
