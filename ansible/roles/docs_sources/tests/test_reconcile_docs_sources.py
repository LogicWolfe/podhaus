"""Unit tests for docs-source slot reconciliation."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.machinery
import importlib.util
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest


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
        self.calls: list[list[str]] = []

    def mounted(self, path: Path) -> bool:
        return path in self.mounts

    def run(self, args: list[str], *, check: bool = True):
        self.calls.append(args)
        if args[:2] == ["mount", "--bind"]:
            self.mounts.add(Path(args[-1]))
        elif args[0] == "umount":
            self.mounts.remove(Path(args[-1]))


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


if __name__ == "__main__":
    unittest.main()
