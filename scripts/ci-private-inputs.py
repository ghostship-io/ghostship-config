#!/usr/bin/env python3
"""Import exact private flake sources using repository-specific read-only keys."""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import private_source


# Private flake inputs mapped to their source repository, scoped read key, and
# optional subdirectory. The deployment consumes the agent repository for the
# ghostship-tools platform builder; the MCP image's shopping policy and icon are
# deployment-owned under modules/self-hosted/private-integrations/.
SOURCES = {
    'ghostship-private-agent': {'repo': 'ghostship-agent', 'key': 'agent', 'dir': None},

}


def main():
    lock_path = Path('flake.lock')
    lock = json.loads(lock_path.read_text())
    nodes = lock['nodes']
    backup = Path(os.environ['RUNNER_TEMP'])/'ghostship-private-lock.json'
    if sys.argv[1:] == ['--restore']:
        originals = json.loads(backup.read_text())
        for name, node in originals.items():
            nodes[name] = node
        lock_path.write_text(json.dumps(lock, indent=2) + '\n')
        return
    credentials = {suffix: os.environ.pop('GHOSTSHIP_' + suffix.upper() + '_READ_KEY', '')
                   for suffix in ('agent', 'assistant')}
    meta_token = os.environ.pop('GITHUB_META_TOKEN', '')
    originals = {name: nodes[name] for name in SOURCES}
    backup.write_text(json.dumps(originals))
    root = Path(tempfile.mkdtemp(prefix='ghostship-ci-sources-', dir=os.environ['RUNNER_TEMP']))
    try:
        # Authenticate the SSH host using GitHub's HTTPS-published public keys.
        host_keys = private_source.github_host_keys(meta_token)
        del meta_token
        known = private_source.known_hosts(root/'known_hosts', host_keys)
        for name, spec in SOURCES.items():
            suffix = spec['key']
            credential = credentials.pop(suffix)
            if not credential:
                raise SystemExit('Missing scoped private-source key: ' + suffix)
            key = root/(suffix + '.key')
            key.write_text(credential + '\n'); key.chmod(0o600)
            del credential
            locked = nodes[name]['locked']
            if locked['type'] != 'github' or locked['owner'] != 'owner' or locked['repo'] != spec['repo']:
                raise SystemExit('Unsupported private source declaration: ' + name)
            if spec['dir'] and locked.get('dir') != spec['dir']:
                raise SystemExit('Unsupported private source directory: ' + name)
            checkout = root/('checkout-' + suffix)
            env = private_source.ssh_environment(key, known)
            private_source.fetch_source(checkout, 'git@github.com:owner/' + spec['repo'] + '.git',
                                        locked['rev'], env)
            key.unlink()
            archive = root/(suffix + '.tar')
            with archive.open('wb') as output:
                subprocess.run(['git', '-C', str(checkout), 'archive', 'FETCH_HEAD'], stdout=output, env=env, check=True)
            source = root/('source-' + suffix); source.mkdir()
            with tarfile.open(archive) as packed:
                packed.extractall(source, filter='data')
            actual = subprocess.check_output(['nix', 'hash', 'path', str(source)], text=True).strip()
            if actual != locked['narHash']:
                raise SystemExit('Pinned private source hash mismatch: ' + suffix)
            # CI-only local Git locks avoid private GitHub archive/API credentials.
            substituted = {
                'type': 'git', 'url': checkout.as_uri(), 'rev': locked['rev'],
                'narHash': locked['narHash'], 'lastModified': locked['lastModified']}
            if spec['dir']:
                substituted['dir'] = spec['dir']
            nodes[name]['locked'] = substituted
            print('Verified pinned private source: ' + name, flush=True)
        lock_path.write_text(json.dumps(lock, indent=2) + '\n')
    finally:
        for key in root.glob('*.key'):
            key.unlink(missing_ok=True)



if __name__ == '__main__':
    main()
