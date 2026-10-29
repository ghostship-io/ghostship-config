"""Select the codex canary without changing any other provider settings."""
import json
import os
from pathlib import Path
import sys
import tempfile


def configure(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('settings symlink is not managed')
    data = json.loads(path.read_text())
    instance = data.get('providerInstances', {}).get('codex')
    if instance is None:
        return  # Candidate images can contain only the non-secret review instance.
    if instance.get('driver') != 'codex':
        raise ValueError('codex instance driver changed')
    config = instance['config']
    target = '/usr/lib/ghostship-provider-launchers/codex'
    current = config.get('binaryPath')
    original = json.loads(os.environ['GHOSTSHIP_PROVIDER_EXECUTABLES'])['codex']
    if current not in ('codex', original, target):
        raise ValueError('codex binaryPath is not the expected original')
    if current == target:
        return
    config['binaryPath'] = target
    fd, name = tempfile.mkstemp(prefix='.settings-provider-', dir=path.parent)
    try:
        os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


if __name__ == '__main__':
    try:
        configure(sys.argv[1])
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise SystemExit('provider-flake setup: codex settings unavailable or unexpected')
