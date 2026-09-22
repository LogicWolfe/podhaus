import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class IndyDeploymentContractTests(unittest.TestCase):
    def resources(self, filename, kind):
        content = tomllib.loads((REPO / "komodo/sync" / filename).read_text())
        return {resource["name"]: resource["config"] for resource in content[kind]}

    def test_green_release_has_a_complete_declared_deployment_path(self):
        repos = self.resources("repos.toml", "repo")
        syncs = self.resources("syncs.toml", "resource_sync")
        procedures = self.resources("procedures.toml", "procedure")
        procedure = procedures["indy-board-push-deploy"]
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
            ["PullRepo", "RunSync", "BatchDeployStack"],
        )
        repo_name = executions[0]["params"]["repo"]
        sync = syncs[executions[1]["params"]["sync"]]
        self.assertEqual(repos[repo_name]["repo"], "LogicWolfe/indy-board")
        self.assertEqual(repos[repo_name]["branch"], "deploy")
        self.assertEqual(sync["linked_repo"], repo_name)
        self.assertEqual(sync["resource_path"], ["stack.toml"])
        self.assertTrue(sync["include_variables"])
        self.assertTrue(sync["include_resources"])
        self.assertFalse(sync["delete"])
        self.assertEqual(executions[2]["params"]["pattern"], "indy-board")


if __name__ == "__main__":
    unittest.main()
