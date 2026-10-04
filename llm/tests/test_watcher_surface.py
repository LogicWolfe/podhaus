"""The watcher's edges: its HTTP surface, its configuration, the parts that read
nvidia-smi and the guest's memory, and the shape of every log line."""

from __future__ import annotations

import http.client
from pathlib import Path
import re
import tempfile
import threading
import unittest

from llm.watcher.guest import Guest
from llm.watcher.gpu import GpuReading, NvidiaSmi
from llm.watcher.settings import Settings
from llm.watcher.web import ControlServer
from watcher_harness import LINUX_ONLY, MEMINFO, Harness, at, environment

T0 = at("12:00:00")


@LINUX_ONLY
class ControlSurface(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(self.addCleanup, model="loaded", start=T0)
        self.harness.tick(T0 + 1)
        surface = ControlServer(self.harness.watcher, port=0)
        surface.start()
        self.addCleanup(surface.close)
        self.port = surface.port

    def request(self, method: str, path: str, headers: dict[str, str] | None = None,
                timeout: float = 5) -> tuple[int, dict[str, str], str]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        self.addCleanup(connection.close)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode()

    def test_the_page_shows_the_state_and_both_buttons(self) -> None:
        status, headers, body = self.request("GET", "/control")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("Serving", body)
        self.assertIn('action="/control/yield"', body)
        self.assertIn('action="/control/resume"', body)

    def test_the_page_asks_for_nothing_outside_control(self) -> None:
        # The ingress forwards only /control and below to the watcher.
        body = self.request("GET", "/control")[2]
        references = re.findall(r'(?:href|src|action)="([^"]*)"', body)
        self.assertTrue(references)
        for reference in references:
            self.assertTrue(reference.startswith(("/control", "data:")), reference)
        self.assertNotIn("url(", body)
        self.assertNotIn("<script", body)
        # Without an icon of its own, a browser asks for /favicon.ico.
        self.assertIn('rel="icon"', body)

    def test_the_buttons_act_and_return_to_the_page(self) -> None:
        status, headers, _ = self.request("POST", "/control/yield")
        self.assertEqual((status, headers["Location"]), (303, "/control"))
        self.assertEqual(self.harness.state, "yielding")
        self.harness.quiet(T0 + 2, T0 + 5)
        self.assertIn("Held", self.request("GET", "/control")[2])
        status, _, _ = self.request("POST", "/control/resume")
        self.assertEqual(status, 303)
        self.assertEqual(self.harness.state, "resuming")

    def test_metrics_carry_every_named_series(self) -> None:
        status, _, body = self.request("GET", "/metrics")
        self.assertEqual(status, 200)
        values = dict(line.rsplit(" ", 1) for line in body.splitlines() if not line.startswith("#"))
        self.assertEqual(values['llm_watcher_state{state="serving"}'], "1")
        for state in ("yielding", "yielded", "resuming"):
            self.assertEqual(values[f'llm_watcher_state{{state="{state}"}}'], "0")
        self.assertEqual(float(values["llm_watcher_last_sample_age_seconds"]), 0)
        self.assertEqual(values["llm_gpu_utilization_percent"], "0")
        self.assertEqual(values["llm_gpu_memory_used_mib"], "4000")
        self.assertEqual(values["llm_gpu_memory_total_mib"], "32607")
        self.assertEqual(float(values["llm_gpu_power_watts"]), 80)
        self.assertEqual(values["llm_gpu_temperature_celsius"], "52")
        self.assertEqual(values["llm_guest_memory_available_mib"], "12288")
        self.assertEqual(values["llm_guest_memory_total_mib"], "25600")
        self.assertEqual(values["llm_pool_tokens"], "0")
        self.assertEqual(values["llm_pool_limit_tokens"], "204800")

    def test_health_answers_200_then_503_with_the_reason(self) -> None:
        self.assertEqual(self.request("GET", "/healthz")[0], 200)
        self.harness.gpu.memory_used_mib = 31200
        self.harness.tick(T0 + 2)
        status, _, body = self.request("GET", "/healthz")
        self.assertEqual((status, body), (503, "vram_at_limit"))

    def test_the_page_and_the_health_check_answer_while_a_tick_is_stuck(self) -> None:
        gpu = self.harness.gpu
        gpu.reading.clear()
        gpu.release.clear()
        self.addCleanup(gpu.release.set)
        stuck = threading.Thread(target=self.harness.tick, args=(T0 + 2,), daemon=True)
        stuck.start()
        self.assertTrue(gpu.reading.wait(timeout=5))
        # Docker's probe gives up after 3 s.
        self.assertEqual(self.request("GET", "/healthz", timeout=3)[0], 200)
        self.assertEqual(self.request("GET", "/control", timeout=3)[0], 200)
        self.assertEqual(self.request("GET", "/metrics", timeout=3)[0], 200)
        gpu.release.set()
        stuck.join(timeout=5)

    def test_cross_site_posts_are_refused(self) -> None:
        refused = (
            {"Sec-Fetch-Site": "cross-site"},
            {"Host": "llm.pod.haus", "Origin": "https://evil.example"},
            {"Host": "127.0.0.1:8085", "Origin": "http://127.0.0.1:9999"},
            {"Host": "llm.pod.haus", "Origin": "null"},
        )
        for headers in refused:
            for path in ("/control/yield", "/control/resume"):
                with self.subTest(headers=headers, path=path):
                    self.assertEqual(self.request("POST", path, headers)[0], 403)
        self.assertEqual(self.harness.state, "serving")

    def test_the_pages_own_posts_are_accepted_through_both_listeners(self) -> None:
        own = (
            {"Host": "llm.pod.haus", "Origin": "https://llm.pod.haus", "Sec-Fetch-Site": "same-origin"},
            {"Host": "127.0.0.1:8085", "Origin": "http://127.0.0.1:8085", "Sec-Fetch-Site": "same-origin"},
        )
        for headers in own:
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", "/control/resume", headers)[0], 303)
        self.assertEqual(self.request("POST", "/control/yield", own[0])[0], 303)
        self.assertEqual(self.harness.state, "yielding")

    def test_other_paths_are_refused(self) -> None:
        self.assertEqual(self.request("GET", "/")[0], 404)
        self.assertEqual(self.request("POST", "/control")[0], 404)


class Configuration(unittest.TestCase):
    """Against the llm-watcher service's environment in llm/compose.yaml."""

    ENVIRONMENT = environment()

    def test_reads_every_setting(self) -> None:
        settings = Settings.from_environ(self.ENVIRONMENT)
        env = self.ENVIRONMENT
        self.assertEqual(settings.server_url, env["LLM_SERVER_URL"])
        self.assertEqual(settings.pool_tokens, int(env["LLM_POOL_TOKENS"]))
        self.assertEqual(settings.activity_threshold_percent, float(env["WATCHER_ACTIVITY_THRESHOLD_PERCENT"]))
        self.assertEqual(settings.vram_limit_mib, int(env["WATCHER_VRAM_LIMIT_MIB"]))
        self.assertEqual(settings.load_timeout_s, float(env["WATCHER_LOAD_TIMEOUT_SECONDS"]))
        self.assertEqual(settings.server_silent_s, float(env["WATCHER_SERVER_SILENT_SECONDS"]))

    def test_compose_sets_exactly_the_settings_the_watcher_reads(self) -> None:
        self.assertEqual(len(self.ENVIRONMENT), len(Settings.__dataclass_fields__))

    def test_every_variable_is_required(self) -> None:
        for name in self.ENVIRONMENT:
            partial = {key: value for key, value in self.ENVIRONMENT.items() if key != name}
            with self.subTest(name), self.assertRaises(KeyError):
                Settings.from_environ(partial)

    def test_a_malformed_number_fails(self) -> None:
        for name in ("LLM_POOL_TOKENS", "WATCHER_QUIET_SECONDS"):
            with self.subTest(name), self.assertRaises(ValueError):
                Settings.from_environ({**self.ENVIRONMENT, name: "sixty"})


class NvidiaSmiOutput(unittest.TestCase):
    def test_reads_one_gpu(self) -> None:
        reading = NvidiaSmi.parse("17, 4368, 32607, 128.51, 45\n")
        self.assertEqual(reading, GpuReading(17, 4368, 32607, 128.51, 45))

    def test_refuses_more_than_one_gpu_or_a_missing_value(self) -> None:
        for output in ("17, 4368, 32607, 128.51, 45\n3, 10, 8192, 20.0, 40\n", "17, 4368, 32607, [N/A], 45\n"):
            with self.subTest(output), self.assertRaises(ValueError):
                NvidiaSmi.parse(output)


class GuestMemory(unittest.TestCase):
    def setUp(self) -> None:
        files = tempfile.TemporaryDirectory()
        self.addCleanup(files.cleanup)
        self.meminfo = Path(files.name) / "meminfo"
        self.meminfo.write_text(MEMINFO)
        self.model_file = Path(files.name) / "model.gguf"
        self.model_file.write_bytes(bytes(65536))

    def test_reads_total_free_and_available(self) -> None:
        memory = Guest(self.meminfo, self.model_file).memory()
        self.assertEqual((memory.total_mib, memory.free_mib, memory.available_mib), (25600, 4096, 12288))
        # File cache counts as used: dropping the model file's cache at a yield
        # is what returns that memory to Windows.
        self.assertEqual(memory.used_mib, 21504)

    @LINUX_ONLY
    def test_drops_the_model_files_cache(self) -> None:
        Guest(self.meminfo, self.model_file).drop_model_file_cache()

    def test_a_missing_model_file_fails_at_start(self) -> None:
        with self.assertRaises(FileNotFoundError):
            Guest(self.meminfo, self.model_file.with_name("absent.gguf"))


@LINUX_ONLY
class LogLines(unittest.TestCase):
    TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

    def test_every_line_is_json_with_the_common_fields(self) -> None:
        h = Harness(self.addCleanup, model="loaded", start=T0)
        for second in range(1, 8):
            h.tick(T0 + second, util=30)
        h.quiet(T0 + 8, T0 + 200)
        lines = h.lines()
        self.assertEqual(
            {line["event"] for line in lines},
            {"state.adopted", "slots.changed", "handoff.yield", "handoff.resume"},
        )
        for line in lines:
            self.assertRegex(line["ts"], self.TS)
            self.assertIn(line["level"], {"info", "warning", "error"})
            self.assertIsInstance(line["msg"], str)
            for key, value in line.items():
                if key.endswith("_ts") and value is not None:
                    self.assertRegex(value, self.TS)


if __name__ == "__main__":
    unittest.main()
