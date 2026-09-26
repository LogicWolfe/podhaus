#!/usr/bin/env python3
"""Exercise real containers with private synthetic torrents; remove every fixture."""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
import uuid


def bencode(value):
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value, dict):
        return b'd' + b''.join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b'e'
    raise TypeError(type(value))


class ContainerPair:
    def __init__(self, engine, web):
        self.engine, self.web = engine, web
        self.prefix = 'podhaus-migration-check-' + uuid.uuid4().hex
        self.destination = '/data/.' + self.prefix
        self.names = [f'{self.prefix}-{i}.mkv' for i in range(3)]
        self.contents = [(name + '\n').encode() * 600 for name in self.names]
        self.hashes = []

    def python(self, source, *args):
        return subprocess.check_output(['docker', 'exec', '-i', self.engine, 'python3', '-c', source, *args], text=True).strip()

    def rpc(self, method, *args):
        source = '''import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('publisher','/scripts/flood-publish.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
method,args=json.loads(sys.argv[1]);print(json.dumps(module.rpc(method,*args)))'''
        return json.loads(self.python(source, json.dumps([method, args])))

    def request(self, path, body):
        source = '''(async()=>{
const auth=await fetch('http://localhost:3000/api/auth/verify');
const cookie=auth.headers.get('set-cookie').split(';')[0];
const response=await fetch('http://localhost:3000'+process.argv[1],{
method:'POST',headers:{cookie:cookie+'; probe=secret-cookie-canary','content-type':'application/json','authorization':'Bearer secret-auth-canary'},body:process.argv[2]});
console.log(JSON.stringify({status:response.status,body:await response.json()}));
})().catch(e=>{console.error(e);process.exit(1)});'''
        result = subprocess.check_output(['docker', 'exec', self.web, 'node', '-e', source, path, json.dumps(body)], text=True)
        return json.loads(result)

    def add(self):
        files = []
        for name, contents in zip(self.names, self.contents, strict=True):
            info = {b'name': name.encode(), b'length': len(contents), b'piece length': 16384,
                    b'pieces': b''.join(hashlib.sha1(contents[i:i + 16384]).digest() for i in range(0, len(contents), 16384)), b'private': 1}
            self.hashes.append(hashlib.sha1(bencode(info)).hexdigest().upper())
            files.append(base64.b64encode(bencode({b'info': info})).decode())
        result = self.request('/api/torrents/add-files', {'files': files, 'destination': self.destination,
                             'tags': ['migration-check'], 'start': False})
        assert result['status'] == 202, result
        for thash in self.hashes:
            assert self.rpc('d.directory', thash) == '/data/torrents'
            assert self.rpc('d.custom', thash, 'publishdir') == self.destination
            assert self.rpc('d.custom1', thash) == 'migration-check'
        print('PASS three-file upload, destination redirect, and tags', flush=True)

    def restart(self):
        thash = self.hashes[0]
        self.rpc('session.save')
        self.rpc('d.custom.set', thash, 'restart_probe', 'changed-after-save')
        self.python('from pathlib import Path;import sys,base64;Path(sys.argv[1]).write_bytes(base64.b64decode(sys.argv[2]))',
                    '/data/torrents/' + self.names[0], base64.b64encode(self.contents[0][:16384]).decode())
        self.rpc('d.check_hash', thash)
        deadline = time.monotonic() + 30
        while self.rpc('d.completed_bytes', thash) != 16384 and time.monotonic() < deadline:
            time.sleep(1)
        assert self.rpc('d.completed_bytes', thash) == 16384
        assert self.rpc('d.complete', thash) == 0
        subprocess.run(['docker', 'stop', '--timeout', '120', self.engine], check=True)
        subprocess.run(['docker', 'start', self.engine], check=True)
        time.sleep(2)
        assert self.rpc('d.completed_bytes', thash) == 16384
        assert self.rpc('d.custom', thash, 'restart_probe') == 'changed-after-save'
        subprocess.run(['docker', 'restart', self.web], check=True)
        time.sleep(2)
        print('PASS container stop preserved incomplete progress and unsaved custom fields', flush=True)
        self.rpc('session.save')
        subprocess.run(['docker', 'kill', '--signal', 'KILL', self.engine], check=True)
        subprocess.run(['docker', 'start', self.engine], check=True)
        time.sleep(2)
        assert self.rpc('d.completed_bytes', thash) == 16384
        print('PASS engine recovery after forced termination', flush=True)

    def complete(self):
        for thash, name, contents in zip(self.hashes, self.names, self.contents, strict=True):
            self.rpc('d.stop', thash)
            self.python('from pathlib import Path;import sys,base64;Path(sys.argv[1]).write_bytes(base64.b64decode(sys.argv[2]))',
                        '/data/torrents/' + name, base64.b64encode(contents).decode())
            self.rpc('d.check_hash', thash)
            self.rpc('d.start', thash)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if all(self.rpc('d.complete', thash) for thash in self.hashes):
                break
            time.sleep(1)
        assert all(self.rpc('d.complete', thash) for thash in self.hashes), 'Hash check did not complete'
        # Hash-checking existing bytes does not emit the network-download completion event.
        for thash in self.hashes:
            self.rpc('event.download.finished', thash)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if all(self.rpc('d.custom', thash, 'pubdone') == '1' for thash in self.hashes):
                break
            time.sleep(1)
        assert all(self.rpc('d.custom', thash, 'pubdone') == '1' for thash in self.hashes), 'Completion hook did not publish'
        for name in self.names:
            self.python('from pathlib import Path;import sys;assert sys.argv[1] in Path("/flood-db/rtorrent-extract.log").read_text()', name)
        for name in self.names:
            self.python('from pathlib import Path;import sys;assert Path(sys.argv[1]).samefile(sys.argv[2])',
                        '/data/torrents/' + name, self.destination + '/' + name)
        print('PASS completion and hardlink publication', flush=True)

    def logging(self):
        result = self.request('/api/torrents/add-files', {'files': [base64.b64encode(b'secret-payload-canary').decode()],
                              'destination': self.destination, 'start': False})
        assert result['status'] >= 400, result
        lines = subprocess.check_output(['docker', 'logs', self.web], stderr=subprocess.STDOUT, text=True).splitlines()
        errors = [json.loads(line) for line in lines if line.startswith('{') and '"msg":"Request failed"' in line]
        assert errors, 'HTTP failure emitted no structured exception'
        error = errors[-1]
        assert error['route'] == '/api/torrents/add-files' and error['statusCode'] == result['status'], error
        assert error['err']['message'] and error['level'] == 50, error
        for canary in ['secret-cookie-canary', 'secret-auth-canary', 'secret-payload-canary', 'c2VjcmV0LXBheWxvYWQtY2FuYXJ5']:
            assert canary not in json.dumps(error), error
        print('PASS structured failure cause, route/status, and input canaries excluded', flush=True)
        print(json.dumps(error), flush=True)

    def cleanup(self):
        loaded = set(self.rpc('download_list'))
        for thash in self.hashes:
            if thash in loaded:
                self.rpc('d.erase', thash)
        source = '''from pathlib import Path;import json,sys
names,destination=json.loads(sys.argv[1])
for name in names:
 Path('/data/torrents',name).unlink(missing_ok=True)
 Path(destination,name).unlink(missing_ok=True)
p=Path(destination)
if p.exists():p.rmdir()'''
        self.python(source, json.dumps([self.names, self.destination]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine')
    parser.add_argument('web')
    parser.add_argument('--restart', action='store_true', help='Restart isolated containers to verify resume state')
    args = parser.parse_args()
    pair = ContainerPair(args.engine, args.web)
    try:
        pair.add()
        if args.restart:
            pair.restart()
        pair.complete()
        pair.logging()
    finally:
        pair.cleanup()
