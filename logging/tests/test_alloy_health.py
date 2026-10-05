"""Alloy's exporter-stall healthcheck, run as Docker runs it.

The healthcheck in logging/compose.shared.yaml reads, from Alloy's own metrics,
how many HTTP requests the clickstack exporter has completed, whatever their
outcome, and fails when that count has not risen since the previous check
(docs/monitoring.html, the exporter-stall healthcheck). This runs that exact
command, with Compose's `$$` escapes undone, inside the locally cached
grafana/alloy image: against an exporter that is delivering, one whose
collector refuses connections, one whose collector stops mid-run, one whose
requests stop returning, one whose requests never returned, and one with
nowhere to keep its state. A collector that is down must leave Alloy healthy,
so its in-memory queue survives for the retry; only requests that never return
may make it unhealthy.

Needs Docker. Without it the Docker cases are skipped with the reason printed.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "logging" / "compose.shared.yaml"
IMAGE = "grafana/alloy:latest"
LABEL = "podhaus.harness=true"
# The component the healthcheck names; every host's exporter carries it.
EXPORTER = 'otelcol.exporter.otlphttp "clickstack"'
# What makes the count rise every minute on a quiet host: Alloy's own metrics,
# scraped every 60 s and sent through that exporter.
SELF_SCRAPE = re.compile(r'prometheus\.scrape "alloy_self" \{[^}]*scrape_interval\s*=\s*"60s"')

# Accepts what the exporter sends and discards it. The receiver must hand it
# to a component that consumes it (a receiver with no output never listens,
# and one feeding a processor with no output answers 503); the debug exporter
# is the smallest, and it is experimental, hence the sink's stability flag.
SINK = """
logging { level = "warn" }

otelcol.receiver.otlp "in" {
  http { endpoint = "0.0.0.0:4318" }
  output { metrics = [otelcol.exporter.debug.drop.input] }
}

otelcol.exporter.debug "drop" {
  verbosity = "basic"
}
"""

# A host's self-scrape and exporter, scraping every second instead of every
# minute so each case takes seconds. TIMEOUT is empty for the hosts' default
# 30 s request timeout, or `timeout = "0s"` for none: the only way to make a
# request never return on purpose.
SHIPPER = """
prometheus.exporter.self "alloy" { }

prometheus.scrape "alloy_self" {
  targets         = prometheus.exporter.self.alloy.targets
  scrape_interval = "1s"
  scrape_timeout  = "1s"
  forward_to     = [otelcol.receiver.prometheus.alloy_self.receiver]
}

otelcol.receiver.prometheus "alloy_self" {
  output { metrics = [otelcol.processor.batch.clickstack.input] }
}

otelcol.processor.batch "clickstack" {
  timeout = "100ms"
  output { metrics = [otelcol.exporter.otlphttp.clickstack.input] }
}

otelcol.exporter.otlphttp "clickstack" {
  client {
    endpoint            = "ENDPOINT"
    disable_keep_alives = true
    TIMEOUT
  }
  // Short backoff keeps a refused collector's attempts dense for the whole
  // run; production's default backoff would leave 3 s windows flat after
  // about 50 s.
  retry_on_failure {
    initial_interval = "100ms"
    max_interval     = "500ms"
    max_elapsed_time = "30m"
  }
}
"""
NO_TIMEOUT = 'timeout = "0s"'

# Collectors that never answer, in the Alloy image's own perl. HOLD accepts
# every connection and keeps it open unanswered. STOPS_ANSWERING resets its
# first three connections, so the exporter completes three failed requests,
# then holds every later one: an exporter whose requests stop returning.
LISTEN = ('my $s = IO::Socket::INET->new(LocalAddr => "0.0.0.0", LocalPort => 4318,'
          ' Listen => 128, ReuseAddr => 1) or die "listen: $!"; my @held; ')
HOLD = LISTEN + "push @held, $s->accept while 1;"
STOPS_ANSWERING = LISTEN + "close $s->accept for 1 .. 3; push @held, $s->accept while 1;"

COMPLETED = re.compile(r"exporter requests completed: (\d+), at the previous check: (\S+)")
ABSENT = "Alloy reports no completed requests by otelcol.exporter.otlphttp.clickstack"
# What the check prints while Alloy is still starting and not yet listening.
NOT_LISTENING = "/dev/tcp/127.0.0.1/12345"


def healthcheck() -> tuple[list[str], str]:
    """The healthcheck's command as Docker receives it, and the tmpfs it keeps state in."""
    alloy = yaml.safe_load(COMPOSE.read_text())["services"]["alloy"]
    kind, *command = alloy["healthcheck"]["test"]
    if kind != "CMD":
        raise AssertionError(f"expected an exec-form healthcheck, got {kind}")
    if any(re.search(r"\$(?!\$)", part.replace("$$", "")) for part in command):
        raise AssertionError("an unescaped $ would be interpolated by Compose")
    [state] = alloy["tmpfs"]
    return [part.replace("$$", "$") for part in command], state


def docker_unavailable() -> str | None:
    if shutil.which("docker") is None:
        return "the docker command is not installed"
    probe = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    if probe.returncode != 0:
        return probe.stderr.decode(errors="replace").strip().splitlines()[-1]
    return None


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60,
                          check=True).stdout


class HostConfigTest(unittest.TestCase):
    """What the check assumes of every host's config.alloy; needs no Docker."""

    def test_every_host_has_the_exporter_and_self_scrape_the_check_relies_on(self) -> None:
        configs = sorted((ROOT / "logging").glob("*/alloy-conf/config.alloy"))
        self.assertEqual(len(configs), 7)
        for config in configs:
            with self.subTest(host=config.parent.parent.name):
                text = config.read_text()
                self.assertTrue(EXPORTER in text, f"{config} has no {EXPORTER}")
                self.assertTrue(SELF_SCRAPE.search(text),
                                f"{config} has no prometheus.scrape \"alloy_self\" every 60s")


class AlloyHealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reason = docker_unavailable()
        if reason:
            raise unittest.SkipTest(f"Docker unavailable: {reason}")
        cls.command, cls.state = healthcheck()
        cls.prefix = f"podhaus-alloy-health-{os.getpid()}"
        cls.workdir = Path(tempfile.mkdtemp(prefix="alloy-health-"))
        cls.addClassCleanup(shutil.rmtree, cls.workdir)
        (cls.workdir / "sink.alloy").write_text(SINK)
        cls.shipper("delivering", "sink:4318")
        cls.shipper("refused", "sink:4319")
        cls.shipper("collector-stops", "stopping-sink:4318")
        cls.shipper("wedging", "stops-answering:4318", NO_TIMEOUT)
        cls.shipper("never-returning", "hold:4318", NO_TIMEOUT)
        cls.shipper("stateless", "sink:4318")
        cls.workdir.chmod(0o755)
        docker("network", "create", "--label", LABEL, cls.prefix)
        cls.addClassCleanup(docker, "network", "rm", cls.prefix)
        for sink in ("sink", "stopping-sink"):
            cls.alloy(sink, "sink.alloy", "--stability.level=experimental")
        cls.run_container("hold", "--entrypoint", "perl", IMAGE, "-MIO::Socket::INET", "-e", HOLD)
        cls.run_container("stops-answering", "--entrypoint", "perl", IMAGE,
                          "-MIO::Socket::INET", "-e", STOPS_ANSWERING)
        for shipper in ("delivering", "refused", "collector-stops", "wedging", "never-returning"):
            cls.alloy(shipper, f"{shipper}.alloy", tmpfs=True)
        cls.alloy("stateless", "stateless.alloy", tmpfs=False)

    @classmethod
    def shipper(cls, name: str, collector: str, timeout: str = "") -> None:
        config = SHIPPER.replace("ENDPOINT", f"http://{cls.prefix}-{collector}")
        (cls.workdir / f"{name}.alloy").write_text(config.replace("TIMEOUT", timeout))

    @classmethod
    def run_container(cls, name: str, *args: str) -> None:
        # No log driver, as for the log schema test: nothing here is for a
        # host's Alloy to ship. Removal goes through the checked wrapper, so a
        # container left behind fails the run.
        container = f"{cls.prefix}-{name}"
        cls.addClassCleanup(docker, "rm", "-f", container)
        docker("run", "-d", "--log-driver", "none", "--label", LABEL, "--name", container,
               "--network", cls.prefix, *args)

    @classmethod
    def alloy(cls, name: str, config: str, *flags: str, tmpfs: bool = False) -> None:
        state = ["--tmpfs", cls.state] if tmpfs else []
        cls.run_container(name, *state, "-v", f"{cls.workdir}:/etc/probe:ro", IMAGE,
                          "run", f"/etc/probe/{config}", "--server.http.listen-addr=0.0.0.0:12345",
                          "--storage.path=/tmp/alloy", *flags)

    def check(self, name: str) -> tuple[int, str]:
        result = subprocess.run(["docker", "exec", f"{self.prefix}-{name}", *self.command],
                                capture_output=True, text=True, timeout=30)
        return result.returncode, (result.stdout + result.stderr).strip()

    def check_until(self, name: str, waiting_on: tuple[str, ...]) -> tuple[int, str]:
        """Checks until the output names none of `waiting_on`."""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            code, output = self.check(name)
            if not any(text in output for text in waiting_on):
                return code, output
            time.sleep(1)
        self.fail(f"{name} still waiting on {waiting_on}; last check said: {output}")

    def first_completion(self, name: str) -> tuple[int, str]:
        """The first check that sees a completed request, which has no history."""
        return self.check_until(name, (NOT_LISTENING, ABSENT))

    def assert_rising(self, name: str, checks: int) -> None:
        """Each of `checks` checks three seconds apart passes with a higher count."""
        for _ in range(checks):
            time.sleep(3)
            code, output = self.check(name)
            match = COMPLETED.search(output)
            self.assertIsNotNone(match, output)
            completed, previous = match.groups()
            self.assertEqual(code, 0, output)
            self.assertGreater(int(completed), int(previous), output)

    def assert_first_check_passes(self, name: str) -> None:
        code, output = self.first_completion(name)
        match = COMPLETED.search(output)
        self.assertIsNotNone(match, output)
        self.assertEqual((code, match[2]), (0, "none"), output)

    def test_a_delivering_exporter_is_healthy(self) -> None:
        self.assert_first_check_passes("delivering")
        self.assert_rising("delivering", checks=2)

    def test_a_collector_refusing_connections_leaves_it_healthy(self) -> None:
        self.assert_first_check_passes("refused")
        self.assert_rising("refused", checks=2)

    def test_a_collector_stopping_mid_run_leaves_it_healthy(self) -> None:
        self.assert_first_check_passes("collector-stops")
        self.assert_rising("collector-stops", checks=1)
        docker("stop", "--timeout", "1", f"{self.prefix}-stopping-sink")
        self.assert_rising("collector-stops", checks=2)

    def test_requests_that_stop_returning_make_it_unhealthy(self) -> None:
        self.assert_first_check_passes("wedging")
        time.sleep(3)
        self.check("wedging")
        time.sleep(3)
        code, output = self.check("wedging")
        match = COMPLETED.search(output)
        self.assertIsNotNone(match, output)
        self.assertEqual(code, 1, output)
        self.assertEqual(match[1], match[2], output)

    def test_requests_that_never_returned_make_it_unhealthy(self) -> None:
        self.check_until("never-returning", (NOT_LISTENING,))
        time.sleep(3)
        code, output = self.check("never-returning")
        self.assertEqual((code, output), (1, ABSENT))

    def test_a_check_with_nowhere_to_keep_its_state_fails(self) -> None:
        code, output = self.first_completion("stateless")
        self.assertEqual(code, 1, output)
        self.assertIn(f"{self.state}/", output)
        self.assertIsNone(COMPLETED.search(output), output)


if __name__ == "__main__":
    unittest.main()
