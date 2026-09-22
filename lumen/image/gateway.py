"""Run Lumen against host worktrees using the shared Podhaus source registry."""

from __future__ import annotations

from functools import cached_property
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from dataclasses import dataclass


SLOT_ROOT = Path("/opt/podhaus/docs-sources")
CONFIG = Path("/etc/podhaus/docs-sources.json")
SKIP_DIRS = {".git", "node_modules", ".venv", "vendor", "target", ".cache"}


@dataclass(frozen=True)
class Source:
    name: str
    source: Path
    required_path: Path
    kind: str

    @classmethod
    def parse(cls, value: dict) -> Source:
        if set(value) != {"name", "source", "required_path", "type"}:
            raise ValueError("Repository source requires name, source, required_path, type")
        if value["type"] not in {"directory", "repository"}:
            raise ValueError("Repository source type must be directory or repository")
        source, required = Path(value["source"]), Path(value["required_path"])
        name = value["name"]
        if not name or name.startswith(".") or "/" in name or "\\" in name:
            raise ValueError("Invalid repository source name")
        if not source.is_absolute() or required.is_absolute() or ".." in required.parts:
            raise ValueError("Invalid repository source path")
        return cls(name, source, required, value["type"])

    @property
    def slot(self) -> Path:
        return SLOT_ROOT / self.name

    def check_available(self) -> None:
        if (self.slot / ".podhaus-source-unavailable").exists():
            raise RuntimeError(f"Repository source unavailable: {self.name}")
        if not (self.slot / self.required_path).exists():
            raise RuntimeError(f"Repository source missing: {self.name}")


@dataclass(frozen=True)
class Repository:
    path: Path
    git_dir: Path

    def worktrees(self) -> list[Path]:
        result = subprocess.run(
            ["git", f"--git-dir={self.git_dir}", "worktree", "list", "--porcelain", "-z"],
            check=True, capture_output=True, text=True,
        )
        paths = [Path(field.removeprefix("worktree "))
                 for field in result.stdout.split("\0") if field.startswith("worktree ")]
        return [self.path if path == self.git_dir.parent else path for path in paths]


class Catalog:
    def __init__(self, config: Path) -> None:
        values = json.loads(config.read_text())
        if not isinstance(values, list) or not values:
            raise ValueError("Repository sources must be a nonempty list")
        sources = [Source.parse(value) for value in values]
        if len({source.name for source in sources}) != len(sources):
            raise ValueError("Repository source names must be unique")
        self.sources: list[Source] = []
        self.unavailable: list[str] = []
        for source in sources:
            try:
                source.check_available()
                self.sources.append(source)
            except RuntimeError as error:
                self.unavailable.append(source.name)
                print(error, file=sys.stderr)

    def repositories(self) -> list[Repository]:
        repositories = []
        for source in self.sources:
            source.check_available()
            if source.kind == "repository":
                repositories.append(Repository(source.source, source.slot / ".git"))
                continue
            for root, directories, _ in os.walk(source.slot):
                path = Path(root)
                if (path / ".git").is_dir():
                    original = source.source / path.relative_to(source.slot)
                    repositories.append(Repository(original, path / ".git"))
                    directories.clear()
                elif (path / ".git").is_file():
                    directories.clear()
                else:
                    directories[:] = [name for name in directories if name not in SKIP_DIRS]
        return repositories

    def available_worktree(self, path: Path) -> bool:
        for source in self.sources:
            if path.is_relative_to(source.source):
                return (source.slot / path.relative_to(source.source)).is_dir()
        result = subprocess.run(
            ["docker", "create", "--mount", f"type=bind,src={path},dst=/probe,readonly",
             "--entrypoint", "true", os.environ["LUMEN_IMAGE"]],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            subprocess.run(["docker", "rm", result.stdout.strip()], check=True, stdout=subprocess.DEVNULL)
            return True
        if f"bind source path does not exist: {path}" in result.stderr:
            return False
        raise RuntimeError(result.stderr.strip())

    @cached_property
    def known_worktrees(self) -> list[Path]:
        paths = sorted({path for repo in self.repositories() for path in repo.worktrees()})
        available = []
        for path in paths:
            if self.available_worktree(path):
                available.append(path)
            else:
                print(f"Skipping missing Git worktree: {path}", file=sys.stderr)
        return available

    def worktrees(self) -> list[Path]:
        return self.known_worktrees

    def mounts(self, worktrees: list[Path]) -> list[str]:
        mounts = []
        for source in self.sources:
            source.check_available()
            mounts += ["--mount", f"type=bind,src={source.slot},dst={source.source},readonly,bind-propagation=rslave"]
        for path in worktrees:
            if not any(path.is_relative_to(source.source) for source in self.sources):
                mounts += ["--mount", f"type=bind,src={path},dst={path},readonly"]
        return mounts


class ForegroundCommand:
    def __init__(self, command: list[str]) -> None:
        self.command = command
        self.process: subprocess.Popen | None = None
        self.termination_signal: int | None = None

    def forward_signal(self, signum: int, frame: object) -> None:
        self.termination_signal = signum
        if self.process is not None:
            self.process.send_signal(signum)

    def run(self) -> int:
        previous = {signum: signal.signal(signum, self.forward_signal)
                    for signum in (signal.SIGTERM, signal.SIGINT)}
        try:
            with subprocess.Popen(self.command, stdin=subprocess.DEVNULL) as process:
                self.process = process
                if self.termination_signal is not None:
                    process.send_signal(self.termination_signal)
                returncode = process.wait()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        if self.termination_signal is not None:
            raise SystemExit(128 + self.termination_signal)
        return returncode


class Runtime:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.uid = str(int(os.environ["LUMEN_UID"]))
        self.gid = str(int(os.environ["LUMEN_GID"]))
        self.image = os.environ["LUMEN_IMAGE"]

    def command(self, args: list[str], cwd: Path, *, detached: bool = False) -> list[str]:
        worktrees = self.catalog.worktrees()
        if args[0] not in {"stdio", "version", "help", "clean"} and not any(cwd.is_relative_to(path) for path in worktrees):
            raise ValueError(f"Not a registered repository worktree: {cwd}")
        command = ["docker", "run", "--pull", "never", "--init", "--security-opt", "label:disable",
                   "--user", f"{self.uid}:{self.gid}", "--network", "dockernet",
                   "--label", "podhaus.lumen=true", "--workdir", str(cwd),
                   "--mount", "type=volume,src=lumen-data,dst=/data",
                   "--env", "HOME=/tmp", "--env", "XDG_DATA_HOME=/data",
                   "--env", "OLLAMA_HOST=http://lumen-ollama:11434",
                   "--env", "LUMEN_EMBED_MODEL=ordis/jina-embeddings-v2-base-code"]
        command += self.catalog.mounts(worktrees)
        if detached:
            name = "lumen-warm-" + hashlib.sha256(str(cwd).encode()).hexdigest()[:16]
            command += ["--detach", "--name", name, "--label", f"podhaus.lumen.worktree={cwd}"]
        else:
            command += ["--rm", "--interactive"]
        return command + ["--entrypoint", "lumen-engine", self.image, *args]

    def warm(self, cwd: Path) -> None:
        name = "lumen-warm-" + hashlib.sha256(str(cwd).encode()).hexdigest()[:16]
        with (Path("/data") / (name + ".lock")).open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.start_warm(cwd, name)

    def start_warm(self, cwd: Path, name: str) -> None:
        existing = subprocess.check_output(
            ["docker", "ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"], text=True,
        ).strip()
        if existing:
            state = json.loads(subprocess.check_output(["docker", "inspect", existing]))[0]["State"]
            if state["Running"]:
                print(f"Lumen indexing already running: {name}", file=sys.stderr)
                return
            if state["ExitCode"] != 0:
                subprocess.run(["docker", "logs", existing], check=True, stdout=sys.stderr)
                print(f"Previous Lumen indexing failed ({state['ExitCode']}); retrying", file=sys.stderr)
            subprocess.run(["docker", "rm", existing], check=True, stdout=subprocess.DEVNULL)
        result = subprocess.check_output(self.command(["index", str(cwd)], cwd, detached=True), text=True)
        print(f"Lumen indexing started: {name} ({result.strip()[:12]})", file=sys.stderr)

    def sweep(self) -> None:
        previous = {signum: signal.signal(signum, self.stop_sweep)
                    for signum in (signal.SIGTERM, signal.SIGINT)}
        try:
            self.index_registered_worktrees()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)

    def stop_sweep(self, signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    def index_registered_worktrees(self) -> None:
        failures = list(self.catalog.unavailable)
        for path in self.catalog.worktrees():
            returncode = ForegroundCommand(self.command(["index", str(path)], path)).run()
            if returncode:
                failures.append(str(path))
        if failures:
            raise RuntimeError("Lumen indexing failed: " + ", ".join(failures))


def main() -> None:
    args = sys.argv[1:]
    if args == ["prepare"]:
        os.chown("/data", int(os.environ["LUMEN_UID"]), int(os.environ["LUMEN_GID"]))
        return
    if not args:
        raise ValueError("Usage: lumen warm | sweep | <lumen command>")
    runtime = Runtime(Catalog(CONFIG))
    if args == ["warm"]:
        runtime.warm(Path(os.environ["LUMEN_CWD"]))
    elif args == ["sweep"]:
        runtime.sweep()
    else:
        os.execvp("docker", runtime.command(args, Path(os.environ["LUMEN_CWD"])))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Lumen failed: {error}", file=sys.stderr)
        sys.exit(1)
