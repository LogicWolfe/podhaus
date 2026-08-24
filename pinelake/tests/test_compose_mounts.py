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
    def test_registered_pinelake_stacks_have_no_relative_host_binds(self) -> None:
        for compose_file in COMPOSE_FILES:
            document = yaml.safe_load(compose_file.read_text())
            for service_name, service in document["services"].items():
                for volume in service.get("volumes", []):
                    source = (
                        volume.get("source", "")
                        if isinstance(volume, dict)
                        else volume.split(":", 1)[0]
                    )
                    with self.subTest(
                        file=compose_file, service=service_name, source=source
                    ):
                        self.assertFalse(source.startswith("."))

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

    def test_flood_labels_resolve_against_pinelake_plex_paths(self) -> None:
        document = yaml.safe_load(
            (ROOT / "pinelake/flood/compose.yaml").read_text()
        )
        environment = document["services"]["pinelake-flood"]["environment"]
        self.assertEqual(
            environment["PLEX_MEDIA_ROOT"],
            "/Volumes/TerraMaster/Torrents",
        )

    def test_pinelake_backup_has_no_onedrive_layer(self) -> None:
        backup_files = (
            ROOT / "backup/pinelake/compose.yaml",
            ROOT / "backup/pinelake/config.json.tmpl",
            ROOT / "backup/pinelake/stack.toml",
        )
        text = "\n".join(path.read_text().lower() for path in backup_files)
        self.assertNotIn("onedrive", text)
        self.assertNotIn("rclone", text)


if __name__ == "__main__":
    unittest.main()
