from pathlib import Path
import json
import tomllib
import unittest
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[2]
PINELAKE_PREFERENCES = ROOT / "pinelake/plex/Preferences.xml.tmpl"
# The identity the predeploy gate and the session gate require of Plex's
# preferences before anything touches the Pine Lake Plex container.
IDENTITY_MANIFEST = ROOT / "ansible/roles/pinelake_macos/files/plex-identity.json"


def pinelake_compose_files() -> list[Path]:
    """Every compose file a stack deployed to the pinelake server runs."""
    files = set()
    for stack_file in ROOT.glob("**/stack.toml"):
        for stack in tomllib.loads(stack_file.read_text()).get("stack", []):
            config = stack["config"]
            if config.get("server") != "pinelake":
                continue
            directory = ROOT / config["run_directory"]
            for name in config.get("file_paths", ["compose.yaml"]):
                files.add((directory / name).resolve())
    return sorted(files)


def volumes(compose_file: Path):
    """Each service's volume entries, with the host side of each."""
    # An overlay file may hold only comments, or name a service it leaves as is.
    document = yaml.safe_load(compose_file.read_text()) or {}
    for service_name, service in document.get("services", {}).items():
        for volume in (service or {}).get("volumes", []):
            source = volume.get("source", "") if isinstance(volume, dict) else volume.split(":", 1)[0]
            yield service_name, volume, source


class TerraMasterMountTests(unittest.TestCase):
    def test_the_stacks_are_found(self) -> None:
        self.assertTrue(pinelake_compose_files())

    def test_pinelake_stacks_have_no_relative_host_binds(self) -> None:
        # Komodo runs Compose inside Periphery, where a relative bind
        # resolves against Periphery's filesystem rather than the Mac's.
        for compose_file in pinelake_compose_files():
            for service_name, _, source in volumes(compose_file):
                with self.subTest(file=compose_file, service=service_name, source=source):
                    self.assertFalse(source.startswith("."))

    def test_external_volume_mounts_refuse_to_create_a_missing_folder(self) -> None:
        found = 0
        for compose_file in pinelake_compose_files():
            for service_name, volume, source in volumes(compose_file):
                if not source.startswith("/Volumes/TerraMaster"):
                    continue
                found += 1
                with self.subTest(file=compose_file, service=service_name, source=source):
                    self.assertIsInstance(volume, dict)
                    self.assertEqual(volume["type"], "bind")
                    self.assertFalse(volume["bind"]["create_host_path"])
        self.assertTrue(found)

    def test_label_sync_names_torrents_by_a_path_plex_mounts(self) -> None:
        """The sync turns rTorrent's /data paths into the paths Plex indexes."""
        rtorrent = yaml.safe_load(
            (ROOT / "pinelake/flood/compose.yaml").read_text()
        )["services"]["pinelake-rtorrent"]
        plex = yaml.safe_load(
            (ROOT / "pinelake/plex/compose.yaml").read_text()
        )["services"]["pinelake-plex"]
        (torrents,) = [
            volume["source"]
            for volume in rtorrent["volumes"]
            if isinstance(volume, dict) and volume["target"] == "/data"
        ]
        plex_sources = {
            volume["source"] for volume in plex["volumes"] if isinstance(volume, dict)
        }
        self.assertEqual(rtorrent["environment"]["PLEX_MEDIA_ROOT"], torrents)
        self.assertIn(torrents, plex_sources)


class PlexPreferencesTests(unittest.TestCase):
    preferences = ET.parse(PINELAKE_PREFERENCES).getroot().attrib

    def test_the_template_carries_the_identity_the_gates_require(self) -> None:
        """A different identity would claim a new server and lock every deploy behind the gates."""
        identity = json.loads(IDENTITY_MANIFEST.read_text())
        self.assertTrue(identity)
        for key, value in identity.items():
            with self.subTest(key=key):
                self.assertEqual(self.preferences[key], value)

    def test_the_advertised_connection_list_is_left_to_the_launch_daemon(self) -> None:
        """`plex-advertise` reconciles it against the Mac's live DHCP address.

        plex-preferences.py merges rather than replaces, so naming
        customConnections in the template would overwrite the daemon's value on
        every deploy and send same-house clients back off the LAN.
        """
        self.assertNotIn("customConnections", self.preferences)


if __name__ == "__main__":
    unittest.main()
