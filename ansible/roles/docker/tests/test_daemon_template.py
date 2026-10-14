"""Contract tests for the docker role's daemon.json template."""

import json
from pathlib import Path
import unittest

import jinja2


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "daemon.json.j2"


def render(*, live_restore: bool, nvidia_gpu: bool) -> dict:
    # trim_blocks matches Ansible's template module default.
    environment = jinja2.Environment(trim_blocks=True, keep_trailing_newline=True)
    text = environment.from_string(TEMPLATE.read_text()).render(
        podhaus_docker_live_restore=live_restore,
        podhaus_docker_nvidia_gpu=nvidia_gpu,
    )
    return json.loads(text)


class DaemonTemplateTest(unittest.TestCase):
    def test_the_gpu_switch_adds_the_nvidia_runtime_and_changes_nothing_else(self) -> None:
        # Docker refuses to start on invalid JSON, and any other drift fires
        # the restart handler on every host without the switch.
        for live_restore in (True, False):
            with self.subTest(live_restore=live_restore):
                without = render(live_restore=live_restore, nvidia_gpu=False)
                with_gpu = render(live_restore=live_restore, nvidia_gpu=True)
                self.assertNotIn("runtimes", without)
                self.assertIn("nvidia", with_gpu.pop("runtimes"))
                self.assertEqual(with_gpu, without)


if __name__ == "__main__":
    unittest.main()
