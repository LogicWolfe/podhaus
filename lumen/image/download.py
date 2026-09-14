"""Install the current upstream release and verify its published checksum."""

import hashlib
import json
import platform
import urllib.request
from pathlib import Path

release = json.load(urllib.request.urlopen("https://api.github.com/repos/ory/lumen/releases/latest"))
architecture = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
name = f"lumen-{release['tag_name'].removeprefix('v')}-linux-{architecture}"
assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
checksums = urllib.request.urlopen(assets["checksums.txt"]).read().decode()
expected = {line.split()[1]: line.split()[0] for line in checksums.splitlines()}[name]
binary = urllib.request.urlopen(assets[name]).read()
if hashlib.sha256(binary).hexdigest() != expected:
    raise RuntimeError(f"Checksum mismatch for {name}")
target = Path("/usr/local/bin/lumen-engine")
target.write_bytes(binary)
target.chmod(0o755)
