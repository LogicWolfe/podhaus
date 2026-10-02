import tomllib
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RepoDeployment:
    """A service whose own repository holds its stack, deployed by a procedure that syncs, then deploys."""

    procedure: str
    forgejo_repo: str
    stack_pattern: str


REPO_DEPLOYMENTS = [
    RepoDeployment("indy-board-push-deploy", "LogicWolfe/indy-board", "indy-board"),
    RepoDeployment("bookbinder-push-deploy", "LogicWolfe/bookbinder", "bookbinder"),
    RepoDeployment("bookcard-push-deploy", "LogicWolfe/bookcard", "bookcard"),
    RepoDeployment("bookshelf-push-deploy", "LogicWolfe/bookshelf", "bookshelf"),
]


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

    def test_each_repo_deployment_has_a_complete_declared_path(self):
        repos = resources("repos.toml", "repo")
        syncs = resources("syncs.toml", "resource_sync")
        procedures = resources("procedures.toml", "procedure")
        for deployment in REPO_DEPLOYMENTS:
            with self.subTest(deployment.procedure):
                self.assert_deployment_path(deployment, repos, syncs, procedures[deployment.procedure])

    def assert_deployment_path(self, deployment, repos, syncs, procedure):
        stages = [stage for stage in procedure["stage"] if stage["enabled"]]
        executions = [
            item["execution"]
            for stage in stages
            for item in stage["executions"]
            if item["enabled"]
        ]
        self.assertTrue(procedure["webhook_enabled"])
        self.assertEqual(
            [execution["type"] for execution in executions],
            ["RunSync", "BatchDeployStack"],
        )
        sync = syncs[executions[0]["params"]["sync"]]
        self.assertEqual(repos[sync["linked_repo"]]["repo"], deployment.forgejo_repo)
        self.assertEqual(sync["resource_path"], ["stack.toml"])
        self.assertTrue(sync["include_variables"])
        self.assertTrue(sync["include_resources"])
        self.assertFalse(sync["delete"])
        self.assertEqual(executions[1]["params"]["pattern"], deployment.stack_pattern)


if __name__ == "__main__":
    unittest.main()
