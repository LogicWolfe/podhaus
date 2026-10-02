"""Contract tests for the docker role's daemon.json template."""

import json
from pathlib import Path
import unittest

import jinja2


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "daemon.json.j2"

# Byte-for-byte what a host without the GPU switch and with live-restore gets.
# A diff here means the restart handler would fire on every such host.
KNOWN_GOOD = """\
{
  "live-restore": true,
  "log-driver": "local",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  }
}
"""


def render(*, live_restore: bool, nvidia_gpu: bool) -> str:
    # trim_blocks matches Ansible's template module default.
    environment = jinja2.Environment(trim_blocks=True, keep_trailing_newline=True)
    return environment.from_string(TEMPLATE.read_text()).render(
        podhaus_docker_live_restore=live_restore,
        podhaus_docker_nvidia_gpu=nvidia_gpu,
    )


class DaemonTemplateTest(unittest.TestCase):
    def test_without_the_gpu_switch_the_file_is_unchanged(self) -> None:
        self.assertEqual(render(live_restore=True, nvidia_gpu=False), KNOWN_GOOD)

    def test_the_gpu_switch_registers_exactly_the_nvidia_runtime(self) -> None:
        for live_restore in (True, False):
            with self.subTest(live_restore=live_restore):
                config = json.loads(render(live_restore=live_restore, nvidia_gpu=True))
                self.assertEqual(
                    config["runtimes"],
                    {"nvidia": {"args": [], "path": "nvidia-container-runtime"}},
                )


if __name__ == "__main__":
    unittest.main()
