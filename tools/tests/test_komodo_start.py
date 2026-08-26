import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class KomodoStartContractTest(unittest.TestCase):
    def test_podhaus_sync_disables_pending_update_alerts(self) -> None:
        script = (REPO_ROOT / "komodo-start").read_text()
        create_sync = script.split('"type": "CreateResourceSync"', 1)[1]
        self.assertIn('"pending_alert": false', create_sync)


if __name__ == "__main__":
    unittest.main()
