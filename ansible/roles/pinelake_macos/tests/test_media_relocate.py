from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "files" / "pinelake-media-relocate"
LOADER = importlib.machinery.SourceFileLoader("pinelake_media_relocate", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeSessionGate:
    def __init__(self, refuse: bool = False) -> None:
        self.calls = 0
        self.refuse = refuse

    def verify(self) -> None:
        self.calls += 1
        if self.refuse:
            raise MODULE.RelocationError("active Plex session")


class MediaRelocateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in (
            "Movies", "TV", "Kids/TV", "Sports",
            "Torrents/Movies", "Torrents/TV", "Torrents/Sports",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_applies_verifies_and_rolls_back_atomic_moves(self) -> None:
        source = self.root / "Kids/TV/Bluey/episode.mkv"
        source.parent.mkdir()
        source.write_bytes(b"episode")
        plan = MODULE.RelocationPlan.build(self.root)
        plan.save(self.manifest)
        gate = FakeSessionGate()
        plan.apply(gate)
        self.assertEqual(gate.calls, 1)
        target = self.root / "Torrents/TV/Bluey/episode.mkv"
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), b"episode")
        self.assertEqual(plan.states(), ["applied"])
        plan.rollback(gate)
        self.assertEqual(gate.calls, 2)
        self.assertEqual(source.read_bytes(), b"episode")
        self.assertFalse(target.exists())

    def test_resumes_interrupted_link_then_unlink(self) -> None:
        source = self.root / "TV/Show/episode.mkv"
        target = self.root / "Torrents/TV/Show/episode.mkv"
        source.parent.mkdir()
        target.parent.mkdir()
        source.write_bytes(b"episode")
        plan = MODULE.RelocationPlan.build(self.root)
        target.hardlink_to(source)
        self.assertEqual(plan.states(), ["linked"])
        plan.apply(FakeSessionGate())
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(), b"episode")

        source.hardlink_to(target)
        self.assertEqual(plan.states(), ["linked"])
        plan.rollback(FakeSessionGate())
        self.assertEqual(source.read_bytes(), b"episode")
        self.assertFalse(target.exists())

    def test_apply_never_overwrites_a_new_destination(self) -> None:
        source = self.root / "Movies/Arrival/movie.mkv"
        target = self.root / "Torrents/Movies/Arrival/movie.mkv"
        source.parent.mkdir()
        target.parent.mkdir()
        source.write_bytes(b"source")
        plan = MODULE.RelocationPlan.build(self.root)
        target.write_bytes(b"new destination")
        with self.assertRaises(MODULE.RelocationError):
            plan.apply(FakeSessionGate())
        self.assertEqual(source.read_bytes(), b"source")
        self.assertEqual(target.read_bytes(), b"new destination")

    def test_equal_collision_deduplicates_and_restores_as_hardlink(self) -> None:
        source = self.root / "Movies/Arrival/movie.mkv"
        target = self.root / "Torrents/Movies/Arrival/movie.mkv"
        source.parent.mkdir()
        target.parent.mkdir()
        source.write_bytes(b"same")
        target.write_bytes(b"same")
        plan = MODULE.RelocationPlan.build(self.root)
        self.assertEqual(plan.operations[0].action, "deduplicate")
        plan.apply(FakeSessionGate())
        self.assertFalse(source.exists())
        plan.rollback(FakeSessionGate())
        self.assertTrue(source.samefile(target))

    def test_active_session_refuses_before_the_first_move(self) -> None:
        source = self.root / "Movies/Arrival/movie.mkv"
        source.parent.mkdir()
        source.write_bytes(b"movie")
        plan = MODULE.RelocationPlan.build(self.root)
        with self.assertRaises(MODULE.RelocationError):
            plan.apply(FakeSessionGate(refuse=True))
        self.assertTrue(source.exists())
        self.assertFalse((self.root / "Torrents/Movies/Arrival/movie.mkv").exists())

    def test_real_session_gate_runs_twice(self) -> None:
        count = self.root / "count"
        count.write_text("0\n", encoding="utf-8")
        executable = self.root / "session-gate"
        executable.write_text(
            "#!/bin/sh\n"
            f"n=$(cat {count}); n=$((n + 1)); echo $n > {count}\n"
            'test "$n" -lt "${REFUSE_AT:-99}"\n',
            encoding="utf-8",
        )
        executable.chmod(0o755)
        MODULE.PlexSessionGate(executable, self.root / "prefs").verify()
        self.assertEqual(count.read_text(encoding="utf-8"), "2\n")

    def test_real_session_gate_propagates_second_check_refusal(self) -> None:
        count = self.root / "count"
        count.write_text("0\n", encoding="utf-8")
        executable = self.root / "session-gate"
        executable.write_text(
            "#!/bin/sh\n"
            f"n=$(cat {count}); n=$((n + 1)); echo $n > {count}\n"
            'test "$n" -ne 2\n',
            encoding="utf-8",
        )
        executable.chmod(0o755)
        with self.assertRaises(MODULE.RelocationError):
            MODULE.PlexSessionGate(executable, self.root / "prefs").verify()
        self.assertEqual(count.read_text(encoding="utf-8"), "2\n")

    def test_different_collision_refuses_without_manifest(self) -> None:
        source = self.root / "Movies/Arrival/movie.mkv"
        target = self.root / "Torrents/Movies/Arrival/movie.mkv"
        source.parent.mkdir()
        target.parent.mkdir()
        source.write_bytes(b"aaaa")
        target.write_bytes(b"bbbb")
        with self.assertRaises(MODULE.RelocationError):
            MODULE.RelocationPlan.build(self.root)
        self.assertFalse(self.manifest.exists())

    def test_overlapping_tv_targets_refuse_before_changes(self) -> None:
        first = self.root / "TV/Show/episode.mkv"
        second = self.root / "Kids/TV/Show/episode.mkv"
        first.parent.mkdir()
        second.parent.mkdir()
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        with self.assertRaises(MODULE.RelocationError):
            MODULE.RelocationPlan.build(self.root)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

    def test_symlink_source_refuses_before_changes(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "Movies/link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(MODULE.RelocationError):
            MODULE.RelocationPlan.build(self.root)


if __name__ == "__main__":
    unittest.main()
