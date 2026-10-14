import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def resources(filename, kind):
    content = tomllib.loads((REPO / "komodo/sync" / filename).read_text())
    return {resource["name"]: resource["config"] for resource in content[kind]}


class RepoDeploymentContractTests(unittest.TestCase):
    def test_every_komodo_repo_tracks_main(self):
        # A push to main deploys: what is on main is what is live. A Repo
        # following any other branch reintroduces a release branch.
        for name, config in resources("repos.toml", "repo").items():
            with self.subTest(name):
                self.assertEqual(config["branch"], "main")

    def test_no_repository_sync_deletes_resources(self):
        # A sync that deletes removes every Komodo resource its own files do
        # not declare, which for a service repository is the rest of the fleet.
        for name, config in resources("syncs.toml", "resource_sync").items():
            with self.subTest(name):
                self.assertFalse(config["delete"])


if __name__ == "__main__":
    unittest.main()
