"""How chain.alloy calls the local model service's two parser modules.

Read from the module files; needs no Docker. The log schema harness runs the
modules themselves on the model service's lines.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

MODULES = Path(__file__).resolve().parents[2] / "logging" / "alloy-modules"


class ChainWiringTest(unittest.TestCase):
    def test_both_modules_are_chained_once_and_the_chain_still_ends_at_its_output(self) -> None:
        chain = (MODULES / "chain.alloy").read_text()
        for name in ("llm_server", "llm_watcher"):
            with self.subTest(module=name):
                self.assertEqual(len(re.findall(rf'^\s*{name} "run"', chain, re.M)), 1)
                self.assertEqual(len(re.findall(rf"\[{name}\.run\.receiver\]", chain)), 1)
        self.assertRegex(chain, r'llm_watcher "run" \{\s*forward_to = argument\.forward_to\.value\s*\}')

    def test_each_module_declares_what_the_chain_calls(self) -> None:
        for file, name in (("llm-server.alloy", "llm_server"), ("llm-watcher.alloy", "llm_watcher")):
            with self.subTest(module=name):
                self.assertIn(f'declare "{name}"', (MODULES / file).read_text())

    def test_each_module_only_touches_its_own_container(self) -> None:
        for file, service in (("llm-server.alloy", "llm-server"), ("llm-watcher.alloy", "llm-watcher")):
            with self.subTest(module=file):
                text = (MODULES / file).read_text()
                self.assertIn(f'selector = "{{service=\\"{service}\\"}}"', text)
                self.assertNotIn('service=\\"caddy\\"', text)


if __name__ == "__main__":
    unittest.main()
