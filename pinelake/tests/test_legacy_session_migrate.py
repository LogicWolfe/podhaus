from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "flood/legacy-session-migrate.py"
SPEC = importlib.util.spec_from_file_location("legacy_session_migrate", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LegacySessionMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sessions = self.root / "sessions"
        self.legacy = self.root / "legacy"
        self.media = self.root / "media"
        self.sessions.mkdir()
        self.legacy.mkdir()
        self.media.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_session(
        self, info_hash: str, name: str, directory: str,
        files: list[str] | None, complete: int = 1,
    ) -> bytes:
        info = {b"name": name.encode()}
        if files is None:
            info[b"length"] = 4
        else:
            info[b"files"] = [
                {b"length": 4, b"path": [part.encode() for part in path.split("/")]}
                for path in files
            ]
        state = {
            b"complete": complete,
            b"custom": {b"addtime": b"1"},
            b"directory": directory.encode(),
            b"loaded_file": f"/config/{info_hash}.torrent".encode(),
        }
        state_content = MODULE.Bencode.encode(state)
        for root in (self.sessions, self.legacy):
            (root / f"{info_hash}.torrent").write_bytes(
                MODULE.Bencode.encode({b"info": info})
            )
            (root / f"{info_hash}.torrent.libtorrent_resume").write_bytes(b"resume")
            (root / f"{info_hash}.torrent.rtorrent").write_bytes(state_content)
        return state_content

    def test_apply_and_rollback_preserve_inodes_and_original_state(self) -> None:
        original = self.write_session(
            "A" * 40, "Release", "/data/TV/Show/Release",
            ["episode.mkv", "release.nfo"],
        )
        old = self.media / "TV/Show/Release"
        old.mkdir(parents=True)
        (old / "episode.mkv").write_bytes(b"film")
        (old / "release.nfo").write_bytes(b"junk")
        inode = (old / "episode.mkv").stat().st_ino

        migration = MODULE.LegacySessionMigration(self.sessions, self.media)
        manifest = migration.plan(1)
        migration.apply(manifest)

        working = self.media / "torrents/Release"
        self.assertEqual((working / "episode.mkv").stat().st_ino, inode)
        self.assertEqual((old / "episode.mkv").stat().st_ino, inode)
        self.assertFalse((old / "release.nfo").exists())
        state = MODULE.Bencode.decode(
            (self.sessions / f"{'A' * 40}.torrent.rtorrent").read_bytes()
        )
        self.assertEqual(state[b"directory"], b"/data/torrents/Release")
        self.assertEqual(state[b"custom"][b"publishdir"], b"/data/TV/Show/Release")
        self.assertEqual(state[b"custom"][b"pubdone"], b"1")

        migration.rollback(manifest, self.legacy)

        self.assertFalse(working.exists())
        self.assertEqual((old / "episode.mkv").stat().st_ino, inode)
        self.assertEqual((old / "release.nfo").read_bytes(), b"junk")
        self.assertEqual(
            (self.sessions / f"{'A' * 40}.torrent.rtorrent").read_bytes(),
            original,
        )

    def test_incomplete_session_is_left_untouched(self) -> None:
        self.write_session("A" * 40, "Complete", "/data/Movies", None)
        incomplete = self.write_session(
            "B" * 40, "Incomplete", "/data/Movies", None, complete=0
        )
        (self.media / "Movies").mkdir()
        (self.media / "Movies/Complete").write_bytes(b"film")
        (self.media / "Movies/Incomplete").write_bytes(b"part")

        migration = MODULE.LegacySessionMigration(self.sessions, self.media)
        manifest = migration.plan(2)
        migration.apply(manifest)

        self.assertEqual(manifest.skipped_incomplete, ("B" * 40,))
        self.assertEqual(
            (self.sessions / f"{'B' * 40}.torrent.rtorrent").read_bytes(),
            incomplete,
        )
        self.assertTrue((self.media / "Movies/Incomplete").exists())
        complete_state = MODULE.Bencode.decode(
            (self.sessions / f"{'A' * 40}.torrent.rtorrent").read_bytes()
        )
        self.assertEqual(complete_state[b"directory"], b"/data/torrents")

    def test_rollback_restores_runtime_mutated_resume_file(self) -> None:
        self.write_session("A" * 40, "Release", "/data/Movies", None)
        (self.media / "Movies").mkdir()
        (self.media / "Movies/Release").write_bytes(b"film")
        migration = MODULE.LegacySessionMigration(self.sessions, self.media)
        manifest = migration.plan(1)
        migration.apply(manifest)

        resume = self.sessions / f"{'A' * 40}.torrent.libtorrent_resume"
        resume.write_bytes(b"runtime mutation")
        migration.rollback(manifest, self.legacy)

        self.assertEqual(resume.read_bytes(), b"resume")

    def test_existing_working_target_refuses_planning(self) -> None:
        self.write_session("A" * 40, "Release", "/data/Movies", None)
        (self.media / "Movies").mkdir()
        (self.media / "Movies/Release").write_bytes(b"film")
        (self.media / "torrents/Release").mkdir(parents=True)

        migration = MODULE.LegacySessionMigration(self.sessions, self.media)
        with self.assertRaisesRegex(MODULE.MigrationError, "already exists"):
            migration.plan(1)


if __name__ == "__main__":
    unittest.main()
