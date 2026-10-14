"""The relay tunnel's security contract, run against the real launcher and
restrictions file in the upstream wstunnel image.

A client holding a relay certificate opens the listeners its rule grants and
no others; a client that trusts a different CA never connects. Certificates
are throwaway ones minted per run. Needs Docker; without it the tests skip
with the reason.
"""

import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import yaml

TUNNEL = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/erebe/wstunnel:latest"
BUSYBOX = "busybox:stable"
SERVER_NAME = "relay.numbat.pod.haus"


def server_service() -> dict:
    return yaml.safe_load((TUNNEL / "numbat/compose.yaml").read_text())["services"][
        "tunnel-server"
    ]


def server_options() -> list[str]:
    """The server container's user, capabilities, security options and
    restrictions path, read from the stack's compose file so the test runs it
    as Numbat does."""
    service = server_service()
    options = ["--user", service["user"]]
    options += ["-e", f"TUNNEL_RESTRICTIONS={service['environment']['TUNNEL_RESTRICTIONS']}"]
    options += [f"--cap-drop={cap}" for cap in service["cap_drop"]]
    options += [f"--cap-add={cap}" for cap in service["cap_add"]]
    options += [f"--security-opt={opt}" for opt in service["security_opt"]]
    return options


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check
    )


def docker_available() -> str | None:
    if shutil.which("docker") is None:
        return "docker is not installed"
    if docker("info", check=False).returncode != 0:
        return "the Docker daemon is not reachable"
    return None


def openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], capture_output=True, check=True)


class Authority:
    """A throwaway CA and the certificates it signs, as base64 strings."""

    def __init__(self, directory: Path, name: str) -> None:
        self.directory = directory
        self.name = name
        self.key = directory / f"{name}-ca.key"
        self.cert = directory / f"{name}-ca.pem"
        openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(self.key))
        openssl(
            "req", "-x509", "-new", "-key", str(self.key), "-days", "1",
            "-subj", f"/CN={name} test CA", "-out", str(self.cert),
        )

    def issue(self, common_name: str, server_name: str | None = None) -> tuple[Path, Path]:
        key = self.directory / f"{self.name}-{common_name}.key"
        request = self.directory / f"{self.name}-{common_name}.csr"
        cert = self.directory / f"{self.name}-{common_name}.pem"
        extensions = self.directory / f"{self.name}-{common_name}.ext"
        usage = "serverAuth" if server_name else "clientAuth"
        san = f"subjectAltName=DNS:{server_name}\n" if server_name else ""
        extensions.write_text(f"extendedKeyUsage={usage}\n{san}")
        openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key))
        openssl("req", "-new", "-key", str(key), "-subj", f"/CN={common_name}", "-out", str(request))
        openssl(
            "x509", "-req", "-in", str(request), "-CA", str(self.cert), "-CAkey", str(self.key),
            "-CAcreateserial", "-days", "1", "-extfile", str(extensions), "-out", str(cert),
        )
        return cert, key


def b64(path: Path) -> str:
    import base64

    return base64.b64encode(path.read_bytes()).decode()


@unittest.skipIf(docker_available() is not None, str(docker_available()))
class TunnelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.run_id = uuid.uuid4().hex[:8]
        cls.network = f"tunnel-test-{cls.run_id}"
        cls.containers: list[str] = []
        cls.temporary = tempfile.TemporaryDirectory()
        certs = Path(cls.temporary.name)
        cls.relay = Authority(certs, "relay")
        cls.rogue = Authority(certs, "rogue")
        server_cert, server_key = cls.relay.issue("server", SERVER_NAME)
        cls.mac = cls.relay.issue("nb-macbook-air")
        docker("network", "create", cls.network)
        cls.start(
            "origin", BUSYBOX, ["--network-alias", "origin"],
            "sh", "-c", "while true; do echo tunnel-ok | nc -l -p 9000; done",
        )
        cls.server = cls.start(
            "server", IMAGE,
            ["--network-alias", SERVER_NAME, "--network-alias", "app.numbat.pod.haus",
             *server_options(),
             "-v", f"{TUNNEL}:/etc/tunnel:ro",
             "-e", f"TUNNEL_CA_CERT_B64={b64(cls.relay.cert)}",
             "-e", f"TUNNEL_CERT_B64={b64(server_cert)}",
             "-e", f"TUNNEL_KEY_B64={b64(server_key)}",
             "--entrypoint", "/etc/tunnel/run-wstunnel"],
            *server_service()["command"],
        )
        time.sleep(2)

    @classmethod
    def tearDownClass(cls) -> None:
        for name in cls.containers:
            docker("rm", "-f", name, check=False)
        docker("network", "rm", cls.network, check=False)
        cls.temporary.cleanup()

    @classmethod
    def start(cls, role: str, image: str, options: list[str], *command: str) -> str:
        name = f"tunnel-test-{cls.run_id}-{role}"
        docker("run", "-d", "--name", name, "--network", cls.network, *options, image, *command)
        cls.containers.append(name)
        return name

    def client(self, role: str, trusted_ca: Path, cert: tuple[Path, Path], listener: str) -> str:
        return self.start(
            role, IMAGE,
            ["-v", f"{TUNNEL}:/etc/tunnel:ro",
             "-e", f"TUNNEL_CA_CERT_B64={b64(trusted_ca)}",
             "-e", f"TUNNEL_CERT_B64={b64(cert[0])}",
             "-e", f"TUNNEL_KEY_B64={b64(cert[1])}",
             "--entrypoint", "/etc/tunnel/run-wstunnel"],
            "client", "--tls-verify-certificate",
            "--tls-certificate=/tmp/tunnel/cert.pem",
            "--tls-private-key=/tmp/tunnel/key.pem",
            "-R", f"tcp://{listener}:origin:9000",
            f"wss://{SERVER_NAME}:2334",
        )

    def read_listener(self, port: int) -> str:
        """What a connection to the port on the server's loopback receives."""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            result = docker(
                "run", "--rm", "--network", f"container:{self.server}", BUSYBOX,
                # Input held open briefly: nc hangs up on end of input,
                # before the reply has come back through the tunnel.
                "sh", "-c", f"sleep 2 | nc -w 3 127.0.0.1 {port}", check=False,
            )
            if "tunnel-ok" in result.stdout:
                return result.stdout.strip()
            time.sleep(1)
        return ""

    def server_log(self) -> str:
        result = docker("logs", self.server, check=False)
        return result.stdout + result.stderr

    def test_a_client_opens_the_listener_its_rule_grants(self):
        self.client("mac-granted", self.relay.cert, self.mac, "127.0.0.1:8449")
        self.assertEqual(self.read_listener(8449), "tunnel-ok")

    def test_a_client_is_refused_a_listener_its_rule_does_not_grant(self):
        self.client("mac-other-port", self.relay.cert, self.mac, "127.0.0.1:8450")
        time.sleep(5)
        self.assertEqual(self.read_listener(8450), "")
        self.assertIn("8450", self.server_log())

    def test_a_client_that_trusts_another_ca_never_connects(self):
        name = self.client("mac-wrong-ca", self.rogue.cert, self.mac, "127.0.0.1:8451")
        time.sleep(5)
        logs = docker("logs", name, check=False)
        self.assertRegex((logs.stdout + logs.stderr).lower(), "certificate|tls|unknown")
        self.assertEqual(self.read_listener(8451), "")

    def test_a_certificate_from_another_ca_is_refused_by_the_server(self):
        rogue_mac = self.rogue.issue("nb-macbook-air")
        self.client("rogue-cert", self.relay.cert, rogue_mac, "127.0.0.1:8452")
        time.sleep(5)
        self.assertEqual(self.read_listener(8452), "")


if __name__ == "__main__":
    unittest.main()
