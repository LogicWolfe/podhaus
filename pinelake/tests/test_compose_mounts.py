from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "backup/pinelake/compose.yaml",
    ROOT / "pinelake/flood/compose.yaml",
    ROOT / "pinelake/plex/compose.yaml",
    ROOT / "pinelake/staging/compose.yaml",
    ROOT / "pinelake/syncthing/compose.yaml",
)


class TerraMasterMountTests(unittest.TestCase):
    def test_external_volume_mounts_use_structured_bind_syntax(self) -> None:
        found = 0
        for compose_file in COMPOSE_FILES:
            document = yaml.safe_load(compose_file.read_text())
            for service_name, service in document["services"].items():
                for volume in service.get("volumes", []):
                    source = volume.get("source") if isinstance(volume, dict) else volume
                    if not source.startswith("/Volumes/TerraMaster"):
                        continue
                    found += 1
                    with self.subTest(file=compose_file, service=service_name, source=source):
                        self.assertIsInstance(volume, dict)
                        self.assertEqual(volume["type"], "bind")
                        self.assertFalse(volume["bind"]["create_host_path"])
        self.assertEqual(found, 23)

    def test_plex_can_see_both_media_ingress_paths(self) -> None:
        document = yaml.safe_load(
            (ROOT / "pinelake/plex/compose.yaml").read_text()
        )
        sources = {
            volume["source"]
            for volume in document["services"]["pinelake-plex"]["volumes"]
            if isinstance(volume, dict)
        }
        self.assertTrue(
            {
                "/Volumes/TerraMaster/Movies",
                "/Volumes/TerraMaster/TV",
                "/Volumes/TerraMaster/Kids",
                "/Volumes/TerraMaster/Sports",
                "/Volumes/TerraMaster/Torrents",
            }.issubset(sources)
        )


if __name__ == "__main__":
    unittest.main()
