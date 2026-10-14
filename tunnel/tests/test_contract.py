"""The relay tunnels' configuration agrees with itself, read statically.

Numbat's restrictions grant each client certificate a set of listeners; each
client stack asks for exactly those; every Pomerium upstream on Numbat's
loopback is served by exactly one tunnel.
"""

import re
import tomllib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TUNNEL = ROOT / "tunnel"
CLIENTS = sorted(p.parent.name for p in TUNNEL.glob("*/compose.yaml") if p.parent.name != "numbat")
# The MacBook's client is chezmoi's (dotfiles: com.podhaus.docs-tunnel).
OUTSIDE_THIS_REPOSITORY = {"nb-macbook-air": {("127.0.0.1", 8449)}}


class TaggedLoader(yaml.SafeLoader):
    pass


TaggedLoader.add_multi_constructor(
    "!",
    lambda loader, tag, node: {
        tag: loader.construct_scalar(node)
        if isinstance(node, yaml.ScalarNode)
        else loader.construct_mapping(node, deep=True)
    },
)


def stack_definition(client: str) -> dict:
    """The client's stack.toml, or its stack.toml.offline while the host is held out of Komodo (docs/runbooks/pinelake.md)."""
    (path,) = (TUNNEL / client).glob("stack.toml*")
    return tomllib.loads(path.read_text())


def rules() -> dict[str, set[tuple[str, int]]]:
    """Each rule's client and the listeners it grants, as (bind, port)."""
    document = yaml.load((TUNNEL / "numbat/restrictions.yaml").read_text(), TaggedLoader)
    granted = {}
    for rule in document["restrictions"]:
        (prefix,) = [m["PathPrefix"] for m in rule["match"]]
        client = re.fullmatch(r"\^(.+)\$", prefix).group(1)
        listeners = set()
        for allowed in rule["allow"]:
            tunnel = allowed["ReverseTunnel"]
            assert tunnel["protocol"] == ["Tcp"], rule["name"]
            for cidr in tunnel["cidr"]:
                bind, mask = cidr.split("/")
                assert mask == "32", cidr
                listeners |= {(bind, port) for port in tunnel["port"]}
        granted[client] = listeners
    return granted


def requested(client: str) -> set[tuple[str, int]]:
    service = next(iter(yaml.safe_load((TUNNEL / client / "compose.yaml").read_text())["services"].values()))
    command = service["command"]
    listeners = set()
    for flag, spec in zip(command, command[1:]):
        if flag == "-R":
            bind, port, *_ = spec.removeprefix("tcp://").split(":")
            listeners.add((bind, int(port)))
    return listeners


def checkout_file(service: dict, container_path: str) -> Path:
    """The file in this repository a container path reaches through the
    service's bind of a checkout directory."""
    for volume in service["volumes"]:
        source, target = volume.split(":")[:2]
        if container_path.startswith(target + "/"):
            parts = Path(source).parts
            # The bind's source is a host's checkout of a directory of this
            # repository; the longest tail of it that exists here is that directory.
            for start in range(1, len(parts)):
                if (ROOT.joinpath(*parts[start:])).is_dir():
                    return ROOT.joinpath(*parts[start:], container_path.removeprefix(target + "/"))
    raise AssertionError(f"no bind of a checkout reaches {container_path}")


def terraform_clients() -> set[str]:
    """The common names terraform/tunnel.tf issues client certificates to."""
    text = (ROOT / "terraform/tunnel.tf").read_text()
    listed = re.search(r"tunnel_clients\s*=\s*toset\(\[(.*?)\]\)", text, re.S).group(1)
    return set(re.findall(r'"([^"]+)"', listed))


class ContractTests(unittest.TestCase):
    def test_each_client_asks_for_exactly_what_its_rule_grants(self):
        granted = rules()
        clients = {**{c: requested(c) for c in CLIENTS}, **OUTSIDE_THIS_REPOSITORY}
        self.assertEqual(set(clients), set(granted))
        for client, listeners in clients.items():
            with self.subTest(client=client):
                self.assertEqual(listeners, granted[client])

    def test_a_listener_has_one_owner(self):
        owners = [listener for listeners in rules().values() for listener in listeners]
        self.assertEqual(len(owners), len(set(owners)))

    def test_every_pomerium_upstream_on_loopback_is_served(self):
        config = (ROOT / "pomerium/config.yaml").read_text()
        upstreams = {("127.0.0.1", int(p)) for p in re.findall(r"to: (?:https|ssh)://127\.0\.0\.1:(\d+)", config)}
        upstreams.discard(("127.0.0.1", 22))  # Numbat's own sshd
        in_use = {l for c in CLIENTS for l in requested(c)} | set().union(*OUTSIDE_THIS_REPOSITORY.values())
        self.assertEqual(upstreams - in_use, set())

    def test_a_launcher_change_redeploys_every_tunnel(self):
        # The launcher sits outside each stack's directory, so only a
        # declared content path puts it in the hash Komodo deploys on.
        for stack in ["numbat", *CLIENTS]:
            with self.subTest(stack=stack):
                directory = TUNNEL / stack
                document = yaml.safe_load((directory / "compose.yaml").read_text())
                (service,) = document["services"].values()
                launcher = checkout_file(service, service["entrypoint"][-1])
                self.assertTrue(launcher.is_file(), launcher)
                hashed = [(directory / path).resolve() for path in document["x-podhaus-content-paths"]]
                self.assertTrue(any(launcher.is_relative_to(path) for path in hashed + [directory]), launcher)

    def test_each_client_uses_its_own_certificate(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                stack = stack_definition(client)
                environment = stack["stack"][0]["config"]["environment"]
                field = client.upper().replace("-", "_")
                self.assertIn(f"TUNNEL_CERT_B64=[[OP__KOMODO__NUMBAT_TUNNEL__{field}_CERT_B64]]", environment)
                self.assertIn(f"TUNNEL_KEY_B64=[[OP__KOMODO__NUMBAT_TUNNEL__{field}_KEY_B64]]", environment)

    def test_terraform_issues_a_certificate_to_every_client(self):
        self.assertEqual(terraform_clients(), set(CLIENTS) | set(OUTSIDE_THIS_REPOSITORY))


if __name__ == "__main__":
    unittest.main()
