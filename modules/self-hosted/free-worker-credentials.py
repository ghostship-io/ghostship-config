#!/usr/bin/env python3
"""Atomically project only declared free-provider variables; never print values."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

FORBIDDEN = {'OPENCODE_API_KEY', 'OPENCODE_GO_API_KEY', 'OLLAMA_API_KEY'}
NAME = re.compile(r'[A-Z][A-Z0-9_]+')
ENTRY = re.compile(r'(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)')


def select(text, names):
    if not isinstance(names, list) or not all(isinstance(name, str) and NAME.fullmatch(name) for name in names):
        raise ValueError('invalid free-provider credential names')
    if FORBIDDEN & set(names):
        raise ValueError('subscription and Console API-key variables are forbidden')
    found = {}
    for line in text.splitlines():
        match = ENTRY.fullmatch(line.strip())
        if match and match[1] in names:
            found[match[1]] = match[2]
    return ''.join(name + '=' + value + '\n' for name, value in sorted(found.items()))


def write(path, text, uid, gid):
    fd, temporary = tempfile.mkstemp(prefix='.free-credentials-', dir=path.parent)
    try:
        os.fchmod(fd, 0o400)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--names', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--uid', type=int, required=True)
    parser.add_argument('--gid', type=int, required=True)
    args = parser.parse_args()
    try:
        selected = select(args.source.read_text(), json.loads(args.names.read_text()))
        write(args.destination, selected, args.uid, args.gid)
    except (OSError, ValueError):
        print('free-provider credential projection failed')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
