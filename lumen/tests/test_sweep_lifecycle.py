import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


GATEWAY = Path(__file__).resolve().parents[1] / 'image'
CHILD = '''import os, pathlib, signal, sys, time
root = pathlib.Path(sys.argv[1])
def stop(signum, frame):
    (root / 'stopped').write_text(str(signum))
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
(root / 'started').write_text(str(os.getpid()))
time.sleep(10)
'''
RUNNER = '''import os, pathlib, sys, time, types
sys.path.insert(0, sys.argv[1])
from gateway import Runtime
root = pathlib.Path(sys.argv[2])
def worktrees():
    if os.environ['TEST_DISCOVERY_DELAY'] == '1':
        (root / 'discovering').touch()
        time.sleep(10)
    return [root, root / 'next']
runtime = Runtime(types.SimpleNamespace(unavailable=[], worktrees=worktrees))
def command(args, cwd):
    if cwd.name == 'next':
        (root / 'continued').touch()
    return [sys.executable, str(root / 'child.py'), str(root)]
runtime.command = command
runtime.sweep()
'''


class SweepLifecycleTests(unittest.TestCase):
    def wait_for(self, path):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not path.exists():
            time.sleep(0.01)
        self.assertTrue(path.exists(), f'Timed out waiting for {path.name}')

    def start_sweep(self, root, discovery_delay='0'):
        (root / 'child.py').write_text(CHILD)
        return subprocess.Popen(
            [sys.executable, '-c', RUNNER, str(GATEWAY), str(root)],
            env={**os.environ, 'LUMEN_UID': '1000', 'LUMEN_GID': '1000', 'LUMEN_IMAGE': 'lumen:local',
                 'TEST_DISCOVERY_DELAY': discovery_delay},
        )

    def terminate_sweep(self, root, signum):
        process = self.start_sweep(root)
        try:
            self.wait_for(root / 'started')
            process.send_signal(signum)
            process.wait(timeout=5)
            self.wait_for(root / 'stopped')
            self.assertEqual((root / 'stopped').read_text(), str(signum))
            self.assertEqual(process.returncode, 128 + signum)
            self.assertFalse((root / 'continued').exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int((root / 'started').read_text()), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if (root / 'started').exists() and not (root / 'stopped').exists():
                try:
                    os.kill(int((root / 'started').read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_termination_reaches_active_child_and_stops_the_sweep(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signum=signum), tempfile.TemporaryDirectory() as temporary:
                self.terminate_sweep(Path(temporary), signum)

    def test_termination_during_discovery_stops_before_starting_a_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = self.start_sweep(root, discovery_delay='1')
            try:
                self.wait_for(root / 'discovering')
                process.terminate()
                self.assertEqual(process.wait(timeout=5), 143)
                self.assertFalse((root / 'started').exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
