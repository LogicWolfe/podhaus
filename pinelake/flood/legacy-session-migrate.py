#!/usr/bin/env python3
"""Move legacy Pinelake torrents behind the shared hardlink publisher."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath


VIDEO_EXTENSIONS = {
    ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg",
    ".mpg", ".ts", ".wmv",
}
SUBTITLE_EXTENSIONS = {".ass", ".idx", ".srt", ".ssa", ".sub", ".vtt"}
PUBLISH_EXTENSIONS = VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS
CONTAINER_ROOT = PurePosixPath("/data")
WORKING_ROOT = CONTAINER_ROOT / "torrents"
LIBRARY_ROOTS = tuple(CONTAINER_ROOT / name for name in ("Movies", "TV", "Kids", "Sports"))


class MigrationError(RuntimeError):
    pass


class Bencode:
    @classmethod
    def decode(cls, content: bytes) -> object:
        value, position = cls._decode_at(content, 0)
        if position != len(content):
            raise MigrationError("bencode document has trailing data")
        return value

    @classmethod
    def _decode_at(cls, content: bytes, position: int) -> tuple[object, int]:
        marker = content[position : position + 1]
        if marker == b"i":
            end = content.index(b"e", position)
            return int(content[position + 1 : end]), end + 1
        if marker == b"l":
            return cls._decode_list(content, position + 1)
        if marker == b"d":
            return cls._decode_dict(content, position + 1)
        colon = content.index(b":", position)
        size = int(content[position:colon])
        start = colon + 1
        return content[start : start + size], start + size

    @classmethod
    def _decode_list(cls, content: bytes, position: int) -> tuple[list[object], int]:
        values = []
        while content[position : position + 1] != b"e":
            value, position = cls._decode_at(content, position)
            values.append(value)
        return values, position + 1

    @classmethod
    def _decode_dict(cls, content: bytes, position: int) -> tuple[dict[bytes, object], int]:
        values = {}
        while content[position : position + 1] != b"e":
            key, position = cls._decode_at(content, position)
            value, position = cls._decode_at(content, position)
            if not isinstance(key, bytes):
                raise MigrationError("bencode dictionary key is not bytes")
            values[key] = value
        return values, position + 1

    @classmethod
    def encode(cls, value: object) -> bytes:
        if isinstance(value, int):
            return b"i" + str(value).encode() + b"e"
        if isinstance(value, bytes):
            return str(len(value)).encode() + b":" + value
        if isinstance(value, list):
            return b"l" + b"".join(cls.encode(item) for item in value) + b"e"
        if isinstance(value, dict):
            parts = (cls.encode(key) + cls.encode(value[key]) for key in sorted(value))
            return b"d" + b"".join(parts) + b"e"
        raise MigrationError(f"unsupported bencode value: {type(value).__name__}")


@dataclasses.dataclass(frozen=True)
class FileIdentity:
    relative_path: str
    device: int
    inode: int
    size: int
    publish: bool


@dataclasses.dataclass(frozen=True)
class TorrentMove:
    info_hash: str
    name: str
    old_base: str
    new_base: str
    publish_directory: str
    original_state_sha256: str
    migrated_state_sha256: str
    torrent_sha256: str
    resume_sha256: str
    missing_members: int
    files: tuple[FileIdentity, ...]


@dataclasses.dataclass(frozen=True)
class MigrationManifest:
    version: int
    expected_sessions: int
    skipped_incomplete: tuple[str, ...]
    torrents: tuple[TorrentMove, ...]

    def save(self, path: Path) -> None:
        payload = json.dumps(dataclasses.asdict(self), indent=2, sort_keys=True) + "\n"
        atomic_write(path, payload.encode())

    @classmethod
    def load(cls, path: Path) -> "MigrationManifest":
        payload = json.loads(path.read_text())
        if payload.get("version") != 1:
            raise MigrationError("unsupported migration manifest version")
        torrents = tuple(
            TorrentMove(
                **{key: value for key, value in item.items() if key != "files"},
                files=tuple(FileIdentity(**record) for record in item["files"]),
            )
            for item in payload["torrents"]
        )
        return cls(
            version=payload["version"],
            expected_sessions=payload["expected_sessions"],
            skipped_incomplete=tuple(payload["skipped_incomplete"]),
            torrents=torrents,
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    os.chmod(temporary, 0o644)
    temporary.replace(path)


class LegacySessionMigration:
    def __init__(self, session_root: Path, media_root: Path) -> None:
        self.session_root = session_root
        self.media_root = media_root

    def plan(self, expected_sessions: int) -> MigrationManifest:
        state_paths = sorted(self.session_root.glob("*.torrent.rtorrent"))
        if len(state_paths) != expected_sessions:
            raise MigrationError(
                f"expected {expected_sessions} sessions, found {len(state_paths)}"
            )
        moves, skipped = [], []
        for state_path in state_paths:
            state = self._dictionary(Bencode.decode(state_path.read_bytes()), state_path)
            if state.get(b"complete") != 1:
                skipped.append(state_path.name.removesuffix(".torrent.rtorrent"))
                continue
            moves.append(self._plan_torrent(state_path, state))
        return MigrationManifest(1, expected_sessions, tuple(skipped), tuple(moves))

    def _plan_torrent(self, state_path: Path, state: dict[bytes, object]) -> TorrentMove:
        info_hash = state_path.name.removesuffix(".torrent.rtorrent")
        torrent_path = self.session_root / f"{info_hash}.torrent"
        resume_path = self.session_root / f"{info_hash}.torrent.libtorrent_resume"
        metainfo = self._dictionary(Bencode.decode(torrent_path.read_bytes()), torrent_path)
        info = self._dictionary(metainfo[b"info"], torrent_path)
        name = self._text(info[b"name"], torrent_path)
        old_directory = PurePosixPath(self._text(state[b"directory"], state_path))
        multi_file = b"files" in info
        old_base = old_directory if multi_file else old_directory / name
        publish_directory = old_base if b"files" in info else old_directory
        new_base = WORKING_ROOT / name
        new_directory = new_base if multi_file else WORKING_ROOT
        self._validate_paths(old_base, new_base, publish_directory)
        files = self._file_identities(self._host_path(old_base))
        missing = self._missing_members(info, self._host_path(old_base))
        migrated = self._migrated_state(
            state, info_hash, new_directory, publish_directory
        )
        return TorrentMove(
            info_hash, name, str(old_base), str(new_base), str(publish_directory),
            sha256(state_path), hashlib.sha256(migrated).hexdigest(),
            sha256(torrent_path), sha256(resume_path), missing, files,
        )

    def _validate_paths(
        self, old_base: PurePosixPath, new_base: PurePosixPath, publish: PurePosixPath
    ) -> None:
        if not any(publish == root or publish.is_relative_to(root) for root in LIBRARY_ROOTS):
            raise MigrationError(f"publish path is outside a library root: {publish}")
        if new_base.parent != WORKING_ROOT:
            raise MigrationError(f"working path is not a direct child of {WORKING_ROOT}")
        if not self._host_path(old_base).exists():
            raise MigrationError(f"legacy data is missing: {old_base}")
        if self._host_path(new_base).exists():
            raise MigrationError(f"working target already exists: {new_base}")

    def _file_identities(self, base: Path) -> tuple[FileIdentity, ...]:
        paths = [base] if base.is_file() else sorted(path for path in base.rglob("*") if path.is_file())
        records = []
        for path in paths:
            stat = path.stat()
            relative = "" if path == base else str(path.relative_to(base))
            publish = path.suffix.lower() in PUBLISH_EXTENSIONS and "sample" not in path.name.lower()
            records.append(FileIdentity(relative, stat.st_dev, stat.st_ino, stat.st_size, publish))
        if not records:
            raise MigrationError(f"legacy data contains no files: {base}")
        return tuple(records)

    def _missing_members(self, info: dict[bytes, object], base: Path) -> int:
        if b"files" not in info:
            return int(not base.is_file())
        members = []
        for item in info[b"files"]:
            record = self._dictionary(item, base)
            parts = [self._text(part, base) for part in record[b"path"]]
            members.append(base.joinpath(*parts))
        return sum(not path.is_file() for path in members)

    def apply(self, manifest: MigrationManifest) -> None:
        for torrent in manifest.torrents:
            self._verify_static_session_files(torrent)
            self._move_and_publish(torrent)
            self._write_migrated_state(torrent)
        self.verify_applied(manifest)

    def _move_and_publish(self, torrent: TorrentMove) -> None:
        old_base = self._host_path(PurePosixPath(torrent.old_base))
        new_base = self._host_path(PurePosixPath(torrent.new_base))
        if not new_base.exists():
            if not old_base.exists():
                raise MigrationError(f"neither source nor target exists for {torrent.info_hash}")
            new_base.parent.mkdir(parents=True, exist_ok=True)
            old_base.rename(new_base)
        for record in torrent.files:
            source = new_base if record.relative_path == "" else new_base / record.relative_path
            self._verify_identity(source, record)
            if not record.publish:
                continue
            target = old_base if record.relative_path == "" else old_base / record.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not os.path.samefile(source, target):
                    raise MigrationError(f"publication collision: {target}")
                continue
            os.link(source, target)

    def _write_migrated_state(self, torrent: TorrentMove) -> None:
        state_path = self.session_root / f"{torrent.info_hash}.torrent.rtorrent"
        current_sha = sha256(state_path)
        if current_sha == torrent.migrated_state_sha256:
            return
        if current_sha != torrent.original_state_sha256:
            raise MigrationError(f"session state drifted: {state_path}")
        state = self._dictionary(Bencode.decode(state_path.read_bytes()), state_path)
        content = self._migrated_state(
            state, torrent.info_hash, self._new_directory(torrent),
            PurePosixPath(torrent.publish_directory),
        )
        atomic_write(state_path, content)

    def verify_applied(self, manifest: MigrationManifest) -> None:
        for torrent in manifest.torrents:
            self._verify_static_session_files(torrent)
            state_path = self.session_root / f"{torrent.info_hash}.torrent.rtorrent"
            if sha256(state_path) != torrent.migrated_state_sha256:
                raise MigrationError(f"migrated session state mismatch: {state_path}")
            self._verify_published(torrent)

    def _verify_published(self, torrent: TorrentMove) -> None:
        old_base = self._host_path(PurePosixPath(torrent.old_base))
        new_base = self._host_path(PurePosixPath(torrent.new_base))
        for record in torrent.files:
            source = new_base if record.relative_path == "" else new_base / record.relative_path
            self._verify_identity(source, record)
            if record.publish:
                target = old_base if record.relative_path == "" else old_base / record.relative_path
                if not target.exists() or not os.path.samefile(source, target):
                    raise MigrationError(f"publication is not the source inode: {target}")

    def _verify_static_session_files(self, torrent: TorrentMove) -> None:
        torrent_path = self.session_root / f"{torrent.info_hash}.torrent"
        resume_path = self.session_root / f"{torrent.info_hash}.torrent.libtorrent_resume"
        if sha256(torrent_path) != torrent.torrent_sha256:
            raise MigrationError(f"torrent file drifted: {torrent_path}")
        if sha256(resume_path) != torrent.resume_sha256:
            raise MigrationError(f"resume file drifted: {resume_path}")

    def rollback(self, manifest: MigrationManifest, legacy_root: Path) -> None:
        for torrent in reversed(manifest.torrents):
            self._rollback_content(torrent)
            self._restore_session_files(torrent, legacy_root)
        for torrent in manifest.torrents:
            self._verify_original_session_files(torrent)

    def _rollback_content(self, torrent: TorrentMove) -> None:
        old_base = self._host_path(PurePosixPath(torrent.old_base))
        new_base = self._host_path(PurePosixPath(torrent.new_base))
        if not new_base.exists():
            if old_base.exists():
                return
            raise MigrationError(f"neither rollback source nor target exists: {torrent.info_hash}")
        for record in torrent.files:
            if not record.publish:
                continue
            source = new_base if record.relative_path == "" else new_base / record.relative_path
            target = old_base if record.relative_path == "" else old_base / record.relative_path
            if target.exists():
                if not os.path.samefile(source, target):
                    raise MigrationError(f"rollback collision: {target}")
                target.unlink()
        self._remove_empty_tree(old_base)
        old_base.parent.mkdir(parents=True, exist_ok=True)
        new_base.rename(old_base)

    def _restore_session_files(self, torrent: TorrentMove, legacy_root: Path) -> None:
        expected = {
            ".torrent": torrent.torrent_sha256,
            ".torrent.libtorrent_resume": torrent.resume_sha256,
            ".torrent.rtorrent": torrent.original_state_sha256,
        }
        for suffix, digest in expected.items():
            source = legacy_root / f"{torrent.info_hash}{suffix}"
            if sha256(source) != digest:
                raise MigrationError(f"legacy session backup drifted: {source}")
            atomic_write(self.session_root / source.name, source.read_bytes())

    def _verify_original_session_files(self, torrent: TorrentMove) -> None:
        expected = {
            ".torrent": torrent.torrent_sha256,
            ".torrent.libtorrent_resume": torrent.resume_sha256,
            ".torrent.rtorrent": torrent.original_state_sha256,
        }
        for suffix, digest in expected.items():
            path = self.session_root / f"{torrent.info_hash}{suffix}"
            if sha256(path) != digest:
                raise MigrationError(f"restored session file mismatch: {path}")

    @staticmethod
    def _new_directory(torrent: TorrentMove) -> PurePosixPath:
        new_base = PurePosixPath(torrent.new_base)
        single_file = len(torrent.files) == 1 and torrent.files[0].relative_path == ""
        return new_base.parent if single_file else new_base

    @staticmethod
    def _remove_empty_tree(path: Path) -> None:
        if path.is_file() or path.is_symlink():
            raise MigrationError(f"unexpected rollback target remains: {path}")
        if not path.exists():
            return
        for root, directories, files in os.walk(path, topdown=False):
            if files:
                raise MigrationError(f"unexpected files remain in rollback target: {root}")
            for directory in directories:
                (Path(root) / directory).rmdir()
        path.rmdir()

    @staticmethod
    def _verify_identity(path: Path, expected: FileIdentity) -> None:
        stat = path.stat()
        actual = (stat.st_dev, stat.st_ino, stat.st_size)
        required = (expected.device, expected.inode, expected.size)
        if actual != required:
            raise MigrationError(f"file identity changed: {path}")

    @staticmethod
    def _migrated_state(
        state: dict[bytes, object], info_hash: str,
        new_directory: PurePosixPath, publish_directory: PurePosixPath,
    ) -> bytes:
        migrated = dict(state)
        custom = dict(migrated.get(b"custom", {}))
        custom[b"publishdir"] = str(publish_directory).encode()
        custom[b"pubdone"] = b"1"
        migrated[b"custom"] = custom
        migrated[b"directory"] = str(new_directory).encode()
        migrated[b"loaded_file"] = f"/flood-db/{info_hash}.torrent".encode()
        return Bencode.encode(migrated)

    def _host_path(self, container_path: PurePosixPath) -> Path:
        try:
            relative = container_path.relative_to(CONTAINER_ROOT)
        except ValueError as exc:
            raise MigrationError(f"container path is outside {CONTAINER_ROOT}: {container_path}") from exc
        return self.media_root.joinpath(*relative.parts)

    @staticmethod
    def _dictionary(value: object, source: object) -> dict[bytes, object]:
        if not isinstance(value, dict):
            raise MigrationError(f"expected bencode dictionary in {source}")
        return value

    @staticmethod
    def _text(value: object, source: object) -> str:
        if not isinstance(value, bytes):
            raise MigrationError(f"expected bencode string in {source}")
        return value.decode("utf-8")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--session-root", type=Path, required=True)
    plan.add_argument("--media-root", type=Path, required=True)
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--expected-sessions", type=int, required=True)
    for name in ("apply", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--session-root", type=Path, required=True)
        command.add_argument("--media-root", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--session-root", type=Path, required=True)
    rollback.add_argument("--media-root", type=Path, required=True)
    rollback.add_argument("--manifest", type=Path, required=True)
    rollback.add_argument("--legacy-session-root", type=Path, required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    migration = LegacySessionMigration(args.session_root, args.media_root)
    if args.command == "plan":
        if args.manifest.exists():
            raise MigrationError(f"manifest already exists: {args.manifest}")
        manifest = migration.plan(args.expected_sessions)
        manifest.save(args.manifest)
        print(f"Planned {len(manifest.torrents)} complete sessions; skipped {len(manifest.skipped_incomplete)} incomplete")
        return
    manifest = MigrationManifest.load(args.manifest)
    if args.command == "apply":
        migration.apply(manifest)
        print(f"Migrated and verified {len(manifest.torrents)} sessions")
    elif args.command == "verify":
        migration.verify_applied(manifest)
        print(f"Verified {len(manifest.torrents)} migrated sessions")
    else:
        migration.rollback(manifest, args.legacy_session_root)
        print(f"Rolled back and verified {len(manifest.torrents)} sessions")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, UnicodeDecodeError, ValueError, MigrationError) as exc:
        raise SystemExit(f"Legacy session migration refused: {exc}")
