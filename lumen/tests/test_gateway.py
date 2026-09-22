import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('gateway', Path(__file__).parents[1] / 'image/gateway.py')
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / 'slots'
        self.sources.mkdir()
        self.original = self.root / 'original'
        self.original.mkdir()
        (self.sources / 'home').symlink_to(self.original, target_is_directory=True)
        self.repo = self.original / 'project'
        self.git('init', str(self.repo))
        self.git('-C', str(self.repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-m', 'Initial')
        self.worktree = self.root / 'external-worktree'
        self.git('-C', str(self.repo), 'worktree', 'add', '--detach', str(self.worktree))
        self.config = self.root / 'sources.json'
        self.config.write_text(json.dumps([{'name':'home','source':str(self.original),'required_path':'.','type':'directory'}]))
        self.addCleanup(patch.stopall)
        patch.object(gateway, 'SLOT_ROOT', self.sources).start()
        patch.object(gateway.Catalog, 'available_worktree', lambda catalog, path: path.is_dir()).start()
        patch.dict(os.environ, LUMEN_UID='1000', LUMEN_GID='1000', LUMEN_IMAGE='lumen:local').start()

    def git(self, *args):
        # A git hook exports its own repository's GIT_DIR and GIT_INDEX_FILE;
        # these temporary repositories must not inherit them.
        env = {name: value for name, value in os.environ.items() if not name.startswith('GIT_')}
        return subprocess.run(['git', *args], check=True, capture_output=True, text=True, env=env)

    def test_main_and_linked_worktree_keep_original_paths(self):
        self.assertEqual(set(gateway.Catalog(self.config).worktrees()), {self.repo, self.worktree})

    def test_engine_mounts_external_worktree_and_shared_git_root_readonly(self):
        runtime = gateway.Runtime(gateway.Catalog(self.config))
        command = runtime.command(['stdio'], self.worktree)
        self.assertIn(f'type=bind,src={self.worktree},dst={self.worktree},readonly', command)
        self.assertIn(f'type=bind,src={self.sources}/home,dst={self.original},readonly,bind-propagation=rslave', command)
        self.assertEqual(command[-3:], ['lumen-engine', 'lumen:local', 'stdio'])

    def test_unknown_worktree_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Not a registered'):
            gateway.Runtime(gateway.Catalog(self.config)).command(['index'], self.root)

    def test_global_stdio_accepts_cwd_outside_registered_worktree(self):
        command = gateway.Runtime(gateway.Catalog(self.config)).command(['stdio'], self.root)
        self.assertEqual(command[command.index('--workdir') + 1], str(self.root))
        self.assertEqual(command[-1], 'stdio')

    def test_unrelated_stale_worktree_does_not_become_mount(self):
        stale = self.root / 'stale'
        self.git('-C', str(self.repo), 'worktree', 'add', '--detach', str(stale))
        import shutil
        shutil.rmtree(stale)
        command = gateway.Runtime(gateway.Catalog(self.config)).command(['stdio'], self.worktree)
        self.assertFalse(any(f'src={stale},' in arg for arg in command))

    def test_unavailable_source_is_visible_and_healthy_repo_still_works(self):
        sources = json.loads(self.config.read_text())
        sources.append({'name':'missing','source':'/absent','required_path':'.git','type':'repository'})
        self.config.write_text(json.dumps(sources))
        with patch('sys.stderr') as stderr:
            catalog = gateway.Catalog(self.config)
        self.assertTrue(stderr.write.called)
        self.assertEqual(catalog.unavailable, ['missing'])
        self.assertIn(self.repo, catalog.worktrees())

    def test_duplicate_source_rejected(self):
        sources = json.loads(self.config.read_text())
        self.config.write_text(json.dumps(sources * 2))
        with self.assertRaisesRegex(ValueError, 'unique'):
            gateway.Catalog(self.config)


class HostProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'home').mkdir()
        self.config = self.root / 'sources.json'
        self.config.write_text(json.dumps([{
            'name': 'home', 'source': '/host/repos', 'required_path': '.', 'type': 'directory',
        }]))
        self.addCleanup(patch.stopall)
        patch.object(gateway, 'SLOT_ROOT', self.root).start()
        patch.dict(os.environ, LUMEN_IMAGE='lumen:local').start()
        self.catalog = gateway.Catalog(self.config)

    def test_registered_path_uses_mounted_slot_without_docker_probe(self):
        (self.root / 'home' / 'live').mkdir()
        with patch.object(gateway.subprocess, 'run') as run:
            self.assertTrue(self.catalog.available_worktree(Path('/host/repos/live')))
            self.assertFalse(self.catalog.available_worktree(Path('/host/repos/missing')))
        run.assert_not_called()

    def test_external_live_worktree_probe_is_removed_without_starting(self):
        with patch.object(gateway.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, stdout='probe-container\n', stderr=''),
            subprocess.CompletedProcess([], 0),
        ]) as run:
            self.assertTrue(self.catalog.available_worktree(Path('/external/live')))
        self.assertEqual(run.call_args_list[0].args[0][1], 'create')
        self.assertEqual(run.call_args_list[1].args[0], ['docker', 'rm', 'probe-container'])

    def test_missing_external_path_is_distinct_from_docker_failure(self):
        path = Path('/external/missing')
        with patch.object(gateway.subprocess, 'run', return_value=subprocess.CompletedProcess(
            [], 1, stdout='', stderr=f'invalid mount config: bind source path does not exist: {path}',
        )) as run:
            self.assertFalse(self.catalog.available_worktree(path))
            self.assertEqual(run.call_count, 1)
        for error in ('permission denied connecting to Docker', 'No such image: lumen:local'):
            with self.subTest(error=error), patch.object(
                gateway.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='', stderr=error),
            ):
                with self.assertRaisesRegex(RuntimeError, error):
                    self.catalog.available_worktree(path)

    def test_failed_probe_cleanup_is_visible(self):
        with patch.object(gateway.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, stdout='probe-container\n', stderr=''),
            subprocess.CalledProcessError(1, ['docker', 'rm', 'probe-container']),
        ]):
            with self.assertRaises(subprocess.CalledProcessError):
                self.catalog.available_worktree(Path('/external/live'))

    def test_known_worktrees_are_probed_once_per_invocation(self):
        repository = Mock()
        repository.worktrees.return_value = [Path('/external/live')]
        with patch.object(self.catalog, 'repositories', return_value=[repository]), patch.object(
            self.catalog, 'available_worktree', return_value=True,
        ) as available:
            self.assertEqual(self.catalog.worktrees(), [Path('/external/live')])
            self.assertEqual(self.catalog.worktrees(), [Path('/external/live')])
        available.assert_called_once_with(Path('/external/live'))


class ConcurrentWarmHarness:
    def __init__(self, directory):
        self.directory = directory
        catalog = Mock()
        catalog.worktrees.return_value = [directory]
        catalog.mounts.return_value = []
        with patch.dict(os.environ, LUMEN_UID='1000', LUMEN_GID='1000', LUMEN_IMAGE='lumen:local'):
            self.runtime = gateway.Runtime(catalog)
        self.running = threading.Event()
        self.barrier = threading.Barrier(2)
        self.launches = []

    def docker_output(self, command, **kwargs):
        if command[1] == 'ps':
            return 'container\n' if self.running.is_set() else ''
        if command[1] == 'inspect':
            return json.dumps([{'State': {'Running': True, 'ExitCode': 0}}])
        if command[1] != 'run':
            raise AssertionError(command)
        self.launches.append(command)
        time.sleep(0.1)
        self.running.set()
        return 'container\n'

    def warm(self):
        self.barrier.wait(timeout=5)
        self.runtime.warm(self.directory)


class WarmConcurrencyTests(unittest.TestCase):
    def test_two_simultaneous_warm_requests_start_only_one_indexer(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            harness = ConcurrentWarmHarness(directory)
            with patch.object(gateway, 'Path', side_effect=lambda value: directory if value == '/data' else Path(value)), \
                    patch.object(gateway.subprocess, 'check_output', side_effect=harness.docker_output), \
                    patch('sys.stderr'), ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(harness.warm) for _ in range(2)]
                for future in futures:
                    future.result(timeout=5)
            self.assertEqual(len(harness.launches), 1)


if __name__ == '__main__':
    unittest.main()
