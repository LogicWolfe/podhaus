from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    ROOT / "backup/pinelake/compose.yaml",
    ROOT / "pinelake/flood/compose.yaml",
    ROOT / "pinelake/plex/compose.yaml",
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
        self.assertEqual(found, 13)

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

    def test_plex_preferences_preserve_identity(self) -> None:
        preferences = ET.parse(
            ROOT / "pinelake/plex/Preferences.xml.tmpl"
        ).getroot().attrib
        self.assertEqual(
            preferences["ProcessedMachineIdentifier"],
            "92311858cdd55fb33583fda2e6fc037e3655da85",
        )

    def test_plex_advertisement_is_owned_by_the_launch_daemon(self) -> None:
        """Nothing in the stack may write the advertised connection list.

        `plex-advertise` reconciles it against the Mac's live DHCP address.
        plex-preferences.py merges rather than replaces, so naming
        customConnections in the template would overwrite the daemon's value on
        every deploy and send same-house clients back off the LAN.
        """
        preferences = ET.parse(
            ROOT / "pinelake/plex/Preferences.xml.tmpl"
        ).getroot().attrib
        self.assertNotIn("customConnections", preferences)
        self.assertNotIn("LanNetworksBandwidth", preferences)
        document = yaml.safe_load(
            (ROOT / "pinelake/plex/compose.yaml").read_text()
        )
        self.assertNotIn(
            "ADVERTISE_IP", document["services"]["pinelake-plex"]["environment"]
        )

    def test_plex_does_not_advertise_a_port_mapping_it_cannot_have(self) -> None:
        """Pine Lake is behind CGNAT, so no inbound port mapping can exist."""
        preferences = ET.parse(
            ROOT / "pinelake/plex/Preferences.xml.tmpl"
        ).getroot().attrib
        self.assertEqual(preferences["ManualPortMappingMode"], "0")
        self.assertNotIn("ManualPortMappingPort", preferences)

    def test_plex_enforces_the_same_preferences_as_bilby(self) -> None:
        """Pine Lake diverges from bilby only where macOS forces it to."""
        shared = (
            "AcceptedEULA",
            "AnonymousMachineIdentifier",
            "CertificateUUID",
            "DlnaEnabled",
            "IPNetworkType",
            "LanguageInCloud",
            "MachineIdentifier",
            "PlexOnlineToken",
            "ProcessedMachineIdentifier",
            "PublishServerOnPlexOnlineKey",
            "TranscoderTempDirectory",
        )
        pinelake = ET.parse(
            ROOT / "pinelake/plex/Preferences.xml.tmpl"
        ).getroot().attrib
        bilby = ET.parse(ROOT / "plex/Preferences.xml.tmpl").getroot().attrib
        for attribute in shared:
            self.assertIn(attribute, pinelake)
            self.assertIn(attribute, bilby)
        for attribute in ("DlnaEnabled", "IPNetworkType", "TranscoderTempDirectory"):
            self.assertEqual(pinelake[attribute], bilby[attribute])

    def test_plex_publishes_its_ports_instead_of_taking_the_vm_namespace(self) -> None:
        """Host mode makes Plex publish every OrbStack bridge as reachable."""
        document = yaml.safe_load(
            (ROOT / "pinelake/plex/compose.yaml").read_text()
        )
        service = document["services"]["pinelake-plex"]
        self.assertNotIn("network_mode", service)
        self.assertIn("32400:32400/tcp", service["ports"])
        self.assertIn("dockernet", service["networks"])

    def test_no_rathole_service_carries_plex(self) -> None:
        """Plex streams never traverse Numbat; the browser route is separate."""
        for template in (
            ROOT / "relay/pinelake/client.toml.tmpl",
            ROOT / "relay/numbat/server.toml.tmpl",
        ):
            self.assertNotIn("pinelake_plex", template.read_text())

    def test_plex_health_rejects_the_native_server_on_the_shared_port(self) -> None:
        document = yaml.safe_load(
            (ROOT / "pinelake/plex/compose.yaml").read_text()
        )
        health_command = document["services"]["pinelake-plex"]["healthcheck"][
            "test"
        ][-1]
        self.assertIn("dpkg-query", health_command)
        self.assertIn("/identity", health_command)
        self.assertIn("/<MediaContainer /", health_command)
        self.assertIn('test "$$actual" = "$$expected"', health_command)

    def test_pinelake_plex_relay_is_fully_retired(self) -> None:
        """Numbat carries Pine Lake's SSH, logs and browser routes — not video.

        The tunnel that once published Plex on Numbat's relay address sent
        every stream through Australia, including same-house playback whenever
        the LAN entry was stale. Plex's own remote access replaces it.
        """
        files = (
            ROOT / "relay/numbat/server.toml.tmpl",
            ROOT / "relay/pinelake/client.toml.tmpl",
            ROOT / "relay/numbat/compose.yaml",
            ROOT / "relay/pinelake/compose.yaml",
            ROOT / "relay/numbat/stack.toml",
            ROOT / "relay/pinelake/stack.toml",
            ROOT / "terraform/pomerium.tf",
        )
        for path in files:
            with self.subTest(path=path):
                self.assertNotIn("PINELAKE_PLEX", path.read_text())
                self.assertNotIn("pinelake_plex", path.read_text())
        firewall = (
            ROOT / "ansible/roles/numbat_edge/templates/podhaus.nft.j2"
        ).read_text()
        self.assertIn("443, 2333 }", firewall)
        self.assertNotIn("32400", firewall)

    def test_pinelake_plex_has_a_protected_browser_route(self) -> None:
        """The UI stays reachable for liveness and playback checks."""
        self.assertIn(
            "plex.pinelake.haus", (ROOT / "pomerium/config.yaml").read_text()
        )
        caddyfile = (ROOT / "caddy/pinelake/Caddyfile").read_text()
        self.assertIn("@plex host plex.pinelake.haus", caddyfile)
        self.assertIn("reverse_proxy @plex pinelake-plex:32400", caddyfile)
        self.assertIn(
            'toset(["plex", "sync", "torrent"])',
            (ROOT / "terraform/dns_pinelake_haus.tf").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
