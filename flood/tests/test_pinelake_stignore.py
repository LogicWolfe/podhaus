#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "pinelake-stignore.py"
SPEC = importlib.util.spec_from_file_location("pinelake_stignore", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


PERMANENT = """// Never send junk
(?d)(?i).DS_Store
(?i)*.sfv
(?i)*.nfo
// Selected media: exact !path entries live only in this slice

// Deny all unselected content
**
"""


class PinelakeIgnoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data = Path(self.temporary.name)
        for relative in ("Movies", "TV", "Kids", "Sports"):
            root = self.data / relative
            root.mkdir()
            (root / ".stignore").write_text(PERMANENT, encoding="utf-8")
        self.reconciler = MODULE.IgnoreReconciler(self.data)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_routes_each_publish_root_to_its_normal_ignore_file(self) -> None:
        changed = self.reconciler.reconcile(
            [
                f"{self.data}/Movies/Arrival (2016)",
                f"{self.data}/TV/Severance",
                f"{self.data}/Kids/Bluey",
                f"{self.data}/Sports/Final",
            ]
        )
        self.assertEqual(changed, 4)
        for root, entry in (
            ("Movies", "!/Arrival (2016)"),
            ("TV", "!/Severance"),
            ("Kids", "!/Bluey"),
            ("Sports", "!/Final"),
        ):
            content = (self.data / root / ".stignore").read_text()
            self.assertIn(entry, content)

    def test_whitelist_stays_between_permanent_ignores_and_final_deny(self) -> None:
        self.reconciler.reconcile([f"{self.data}/Movies/Arrival (2016)"])
        lines = (self.data / "Movies" / ".stignore").read_text().splitlines()
        self.assertLess(lines.index("(?i)*.nfo"), lines.index("!/Arrival (2016)"))
        self.assertLess(lines.index("!/Arrival (2016)"), lines.index("**"))

    def test_reconciliation_is_insert_only_sorted_and_idempotent(self) -> None:
        paths = [f"{self.data}/TV/zulu", f"{self.data}/TV/Alpha"]
        self.assertEqual(self.reconciler.reconcile(paths), 1)
        first = (self.data / "TV" / ".stignore").read_text()
        self.assertLess(first.index("!/Alpha"), first.index("!/zulu"))
        self.assertEqual(self.reconciler.reconcile(paths), 0)
        self.assertEqual((self.data / "TV" / ".stignore").read_text(), first)

    def test_unknown_publish_root_fails_before_any_write(self) -> None:
        before = {path: path.read_text() for path in self.data.glob("*/.stignore")}
        with self.assertRaises(MODULE.IgnoreContractError):
            self.reconciler.reconcile([f"{self.data}/Documentaries/Unknown"])
        self.assertEqual({path: path.read_text() for path in before}, before)

    def test_missing_or_malformed_contract_fails_before_any_write(self) -> None:
        malformed = self.data / "Sports" / ".stignore"
        malformed.write_text("!Final\n**\n**\n", encoding="utf-8")
        movie = self.data / "Movies" / ".stignore"
        before = movie.read_text()
        with self.assertRaises(MODULE.IgnoreContractError):
            self.reconciler.reconcile([f"{self.data}/Movies/Arrival (2016)"])
        self.assertEqual(movie.read_text(), before)

    def test_receiver_mode_does_nothing(self) -> None:
        with mock.patch.dict(
            os.environ,
            {MODULE.SOURCE_MODE_ENV: "false"},
            clear=True,
        ):
            with mock.patch.object(MODULE, "IgnoreReconciler") as reconciler:
                MODULE.run()
        reconciler.assert_not_called()

    def test_missing_mode_fails_closed(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MODULE.IgnoreContractError):
                MODULE.run()


if __name__ == "__main__":
    unittest.main()
