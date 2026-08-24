#!/usr/bin/env python3
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROLE_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROLE_DIR / "files" / "plex-preferences-convert"
IDENTITY = {
    "MachineIdentifier": "c9d75740-0fd3-4bba-9874-be61f5dc8d38",
    "ProcessedMachineIdentifier": "92311858cdd55fb33583fda2e6fc037e3655da85",
    "AnonymousMachineIdentifier": "166ee17f-2122-4dcf-9d5e-38961c51ff25",
    "CertificateUUID": "5801df40ceea4deaaefd8bd027fc22ff",
}


class PlexPreferencesConvertTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "com.plexapp.plexmediaserver.plist"
        self.manifest = self.root / "identity.json"
        self.server_dir = self.root / "Plex Media Server"
        database_dir = self.server_dir / "Plug-in Support" / "Databases"
        database_dir.mkdir(parents=True)
        (database_dir / "com.plexapp.plugins.library.db").write_bytes(b"sqlite")

        preferences = {
            **IDENTITY,
            "PlexOnlineToken": "secret-token",
            "FriendlyName": "Pine Lake",
            "ManualPortMappingMode": True,
            "ManualPortMappingPort": 32400,
        }
        with self.source.open("wb") as stream:
            plistlib.dump(preferences, stream)
        self.manifest.write_text(json.dumps(IDENTITY), encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--source-plist",
                str(self.source),
                "--server-dir",
                str(self.server_dir),
                "--expected-identity",
                str(self.manifest),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_converts_exact_identity_and_scalar_preferences(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        attrs = ET.parse(self.server_dir / "Preferences.xml").getroot().attrib
        self.assertEqual(attrs["MachineIdentifier"], IDENTITY["MachineIdentifier"])
        self.assertEqual(
            attrs["ProcessedMachineIdentifier"],
            IDENTITY["ProcessedMachineIdentifier"],
        )
        self.assertNotEqual(
            attrs["MachineIdentifier"], attrs["ProcessedMachineIdentifier"]
        )
        self.assertEqual(attrs["ManualPortMappingMode"], "1")
        self.assertEqual(attrs["ManualPortMappingPort"], "32400")
        self.assertEqual(attrs["PlexOnlineToken"], "secret-token")
        self.assertNotIn("secret-token", result.stdout + result.stderr)

    def test_refuses_identity_mismatch_without_writing(self) -> None:
        preferences = plistlib.loads(self.source.read_bytes())
        preferences["ProcessedMachineIdentifier"] = "wrong"
        self.source.write_bytes(plistlib.dumps(preferences))
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ProcessedMachineIdentifier", result.stderr)
        self.assertFalse((self.server_dir / "Preferences.xml").exists())

    def test_refuses_missing_database(self) -> None:
        (
            self.server_dir
            / "Plug-in Support"
            / "Databases"
            / "com.plexapp.plugins.library.db"
        ).unlink()
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("database", result.stderr)
        self.assertFalse((self.server_dir / "Preferences.xml").exists())

    def test_preserves_container_owned_preferences_on_repeat_run(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        target = self.server_dir / "Preferences.xml"
        attrs = ET.parse(target).getroot().attrib
        attrs["ContainerOwnedCanary"] = "preserve-me"
        ET.ElementTree(ET.Element("Preferences", attrs)).write(
            target, encoding="utf-8", xml_declaration=True
        )

        second = self._run()
        self.assertEqual(second.returncode, 0, second.stderr)
        rerendered = ET.parse(target).getroot().attrib
        self.assertEqual(rerendered["ContainerOwnedCanary"], "preserve-me")


if __name__ == "__main__":
    unittest.main()
