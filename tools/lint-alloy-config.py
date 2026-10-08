#!/usr/bin/env python3
'''
Lint every Alloy config under logging/ with Alloy itself, in the
grafana/alloy:latest image the hosts run.

  - Format: every host config and every shared module must be exactly what
    `alloy fmt` prints, so a diff shows what changed, not layout.
  - `alloy validate` on the module directory: every module's own blocks and
    the calls between modules.
  - Load: each host config, unmodified, is started with the modules mounted
    where the hosts mount them, and must load. `alloy validate` on a host
    config does not open the modules it imports, so a misspelled argument to
    a module, a call to a module that does not exist or a reference to an
    export it does not have would pass it; starting Alloy opens them, and
    such a fault ends the process at once with "could not perform the
    initial load". A config that is still running at the deadline has
    loaded, since a load failure exits immediately. The container has no
    network and none of a host's environment values, certificates, files or
    Docker socket; those make components unhealthy, never the load fail, so
    an endpoint or a file is first used when the host's Alloy starts.

The log schema harness in logging/tests runs the modules on real lines.

Needs Docker. Without it the lint is skipped with the reason printed, as the
logging tests are. Exits 1 on a finding, 0 otherwise.
'''
from __future__ import annotations

from dataclasses import dataclass
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parent.parent
LOGGING = REPO_ROOT / "logging"
MODULES = LOGGING / "alloy-modules"
IMAGE = "grafana/alloy:latest"
DIFF_LINES = 40
LOAD_SECONDS = 60
FIRST_PORT = 12345


@dataclass(frozen=True)
class Finding:
    path: str
    problem: str


@dataclass(frozen=True)
class LoadRun:
    """One host config being started, and where its output goes."""

    config: Path
    port: int
    output: Path
    process: subprocess.Popen[bytes]


def docker_unavailable() -> str | None:
    if shutil.which("docker") is None:
        return "the docker command is not installed"
    probe = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=30)
    if probe.returncode != 0:
        return f"`docker info` exited {probe.returncode}: {probe.stderr.strip()}"
    return None


def shown(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def in_container(path: Path) -> str:
    """Where a file under logging/ is inside the lint container."""
    return f"/logging/{path.relative_to(LOGGING).as_posix()}"


class AlloyContainer:
    """One grafana/alloy container the checks run in, with logging/ mounted, and the modules
    also at /etc/alloy-modules, where every host config imports them from."""

    def __init__(self) -> None:
        self.name = f"podhaus-alloy-lint-{os.getpid()}"
        self.started: list[subprocess.Popen[bytes]] = []
        # No network, no log driver and the harness label: nothing here may
        # reach anything, and nothing is for a host's Alloy to read
        # (docker-logs.alloy drops the label). It sleeps rather than runs,
        # so a lint that dies leaves it behind for ten minutes at most.
        # SELinux labelling is off for this container alone: an enforcing host
        # otherwise denies it the checkout, and relabelling with :z would
        # rewrite the checkout's own labels.
        subprocess.run([
            "docker", "run", "-d", "--rm", "--network", "none", "--log-driver", "none",
            "--security-opt", "label=disable",
            "--label", "podhaus.harness=true", "--name", self.name, "--entrypoint", "sleep",
            "-v", f"{LOGGING}:/logging:ro", "-v", f"{MODULES}:/etc/alloy-modules:ro",
            IMAGE, "600",
        ], capture_output=True, text=True, timeout=300, check=True)

    def alloy(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["docker", "exec", self.name, "/bin/alloy", *args],
                              capture_output=True, text=True, timeout=60)

    def version(self) -> str:
        """The release, from the first line of `alloy --version`: "alloy, version v1.20.1 (branch: …)"."""
        return self.alloy("--version").stdout.split()[2]

    def start(self, config: Path, port: int, output: Path) -> LoadRun:
        with output.open("wb") as sink:
            process = subprocess.Popen([
                "docker", "exec", self.name, "/bin/alloy", "run", in_container(config),
                f"--server.http.listen-addr=127.0.0.1:{port}", f"--storage.path=/tmp/load-{port}",
            ], stdout=sink, stderr=subprocess.STDOUT)
        self.started.append(process)
        return LoadRun(config, port, output, process)

    def ready(self, port: int) -> bool:
        request = (f'exec 3<>/dev/tcp/127.0.0.1/{port} && printf "GET /-/ready HTTP/1.0\\r\\n\\r\\n" >&3 '
                   f'&& grep -q "Alloy is ready" <&3')
        return subprocess.run(["docker", "exec", self.name, "bash", "-c", request],
                              capture_output=True, timeout=30).returncode == 0

    def remove(self) -> None:
        """Removes the container, which ends every Alloy started in it."""
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, timeout=60, check=True)
        for process in self.started:
            process.wait(timeout=30)


def check_format(alloy: AlloyContainer, path: Path) -> Finding | None:
    result = alloy.alloy("fmt", in_container(path))
    if result.returncode != 0:
        return Finding(shown(path), "cannot be parsed by `alloy fmt`:\n"
                       + result.stderr.replace("/logging/", "logging/").strip())
    written = path.read_text()
    if result.stdout == written:
        return None
    diff = list(difflib.unified_diff(written.splitlines(), result.stdout.splitlines(),
                                     shown(path), "alloy fmt", lineterm=""))
    more = len(diff) - DIFF_LINES
    shortened = diff[:DIFF_LINES] + ([f"... {more} more diff lines"] if more > 0 else [])
    return Finding(shown(path), "is not formatted as `alloy fmt` prints it; replace it with the "
                                "formatter's output:\n" + "\n".join(shortened))


def check_modules_validate(alloy: AlloyContainer) -> Finding | None:
    result = alloy.alloy("validate", in_container(MODULES))
    if result.returncode == 0:
        return None
    report = (result.stderr + result.stdout).replace("/logging/", "logging/").strip()
    return Finding(f"{shown(MODULES)}/", f"fails `alloy validate`:\n{report}")


def load_failure(run: LoadRun) -> Finding:
    """What Alloy said before it exited: its `Error:` lines and the errors it logged."""
    output = run.output.read_text(errors="replace").replace("/logging/", "logging/")
    said = [line for line in output.splitlines() if line.startswith("Error:") or "level=error" in line]
    return Finding(shown(run.config), f"does not load beside the modules (Alloy exited "
                                      f"{run.process.returncode}):\n" + "\n".join(said[-10:]))


def check_loads(alloy: AlloyContainer, configs: list[Path], outputs: Path) -> list[Finding]:
    pending = [alloy.start(config, FIRST_PORT + i, outputs / f"{config.parent.parent.name}.log")
               for i, config in enumerate(configs)]
    findings: list[Finding] = []
    deadline = time.monotonic() + LOAD_SECONDS
    while pending and time.monotonic() < deadline:
        for run in list(pending):
            if run.process.poll() is not None:
                findings.append(load_failure(run))
                pending.remove(run)
            elif alloy.ready(run.port):
                pending.remove(run)
        time.sleep(0.5)
    return findings


def run_checks(alloy: AlloyContainer, configs: list[Path], modules: list[Path],
               outputs: Path) -> list[Finding]:
    findings = [f for f in (check_format(alloy, path) for path in configs + modules) if f]
    invalid_modules = check_modules_validate(alloy)
    if invalid_modules:
        return findings + [invalid_modules]
    return findings + check_loads(alloy, configs, outputs)


def main() -> int:
    reason = docker_unavailable()
    if reason:
        print(f"alloy-config lint: SKIPPED, Docker is not available ({reason})")
        return 0
    configs = sorted(LOGGING.glob("*/alloy-conf/config.alloy"))
    modules = sorted(MODULES.glob("*.alloy"))
    alloy = AlloyContainer()
    with tempfile.TemporaryDirectory(prefix="podhaus-alloy-lint-") as outputs:
        try:
            version = alloy.version()
            findings = run_checks(alloy, configs, modules, Path(outputs))
        finally:
            alloy.remove()
    if findings:
        print(f"alloy-config lint: FAILED under alloy {version}", file=sys.stderr)
        for finding in findings:
            print(f"\n{finding.path} {finding.problem}", file=sys.stderr)
        return 1
    print(f"alloy-config lint: OK under alloy {version}: {len(configs)} host configs and "
          f"{len(modules)} modules formatted, the modules validated, every host config loaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
