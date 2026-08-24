#!/usr/bin/env python3
from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]


class EntrypointEnvironmentTest(unittest.TestCase):
    def test_every_rathole_template_variable_is_rendered(self) -> None:
        variables = set()
        for template in ROOT.glob("**/*.toml.tmpl"):
            if "relay" not in template.parts:
                continue
            variables.update(re.findall(r"\$\{(RATHOLE_[A-Z0-9_]+)\}", template.read_text()))
        entrypoint = (ROOT / "relay" / "entrypoint.sh").read_text()
        rendered = set(re.findall(r"\$\{(RATHOLE_[A-Z0-9_]+)\}", entrypoint))
        self.assertEqual(variables - rendered, set())


if __name__ == "__main__":
    unittest.main()
