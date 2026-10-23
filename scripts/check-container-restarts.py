#!/usr/bin/env python3
"""Compare generated systemd unit directories and report container restart causes.

Run on the target with BEFORE/AFTER ending in etc/systemd/system. This reads
unit text and referenced store scripts only; it never reads environment files.
Podman upgrades are an accepted restart trigger.
"""
import argparse
from pathlib import Path
import re

STORE_FILE = re.compile(r"/nix/store/[a-z0-9]{32}-[^\s\"'`;:]+")


def closure_text(text, seen=None):
    seen = set() if seen is None else seen
    result = [text]
    for match in STORE_FILE.findall(text):
        path = Path(match)
        if match in seen or not path.is_file() or path.stat().st_size > 1024 * 1024:
            continue
        seen.add(match)
        # Only follow executable scripts, never credentials/config projections.
        with path.open('rb') as stream:
            if stream.read(2) != b'#!':
                continue
        result.append(closure_text(path.read_text(errors='replace'), seen))
    return '\n'.join(result)


def shared_triggers(text):
    expanded = closure_text(text)
    triggers = []
    if re.search(r'/nix/store/[a-z0-9]{32}-source(?:/tools|["\s])', expanded):
        triggers.append('whole agent source')
    if 'ghostship-dashboard-sync' in expanded or ('ghostship-config set' in expanded
        and any(path in expanded for path in ['/srv/apps/homepage', '/srv/apps/muximux'])):
        triggers.append('dashboard reconciliation inside container unit')
    return triggers


def report(before, after):
    for directory in [before, after]:
        if not Path(directory).is_dir():
            raise ValueError('unit directory does not exist: ' + str(directory))
    previous = {path.name: path.read_text() for path in Path(before).glob('*.service')}
    current = {path.name: path.read_text() for path in Path(after).glob('*.service')}
    changed = {name for name in previous.keys() | current.keys()
               if previous.get(name) != current.get(name)}
    stopped = {name for name in changed
               if not any(flag in current.get(name, '') for flag in
                          ['X-RestartIfChanged=false', 'X-ReloadIfChanged=true'])}
    reasons = {name: ['unit changed'] for name in stopped}
    # A restart of a required helper can stop a container even if its own unit
    # did not change. Wants/After alone do not propagate stops.
    while True:
        added = set()
        for name, text in current.items():
            dependencies = re.findall(r'^(?:Requires|BindsTo|PartOf)=(.*)$', text, re.M)
            affected = sorted(set(' '.join(dependencies).split()) & stopped)
            if affected and name not in stopped:
                added.add(name)
                reasons[name] = ['dependency: ' + ', '.join(affected)]
        if not added:
            break
        stopped |= added
    rows = []
    for name in sorted(previous.keys() | current.keys()):
        if not name.startswith('podman-'):
            continue
        why = reasons.get(name, [])
        publisher = 'ghostship-runtime-' + name.removeprefix('podman-')
        # The publisher only restarts when its current code pointer changes;
        # a publisher unit diff alone is a candidate, not proof of recreation.
        if publisher in changed:
            why = why + ['runtime publisher changed (restarts only for changed code)']
        rows.append((name, why, shared_triggers(current.get(name, ''))))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before')
    parser.add_argument('after')
    args = parser.parse_args()
    failed = False
    for name, reasons, violations in report(args.before, args.after):
        print(name + ': ' + ('; '.join(reasons) if reasons else 'unchanged'))
        for violation in violations:
            print('  unrelated restart trigger: ' + violation)
            failed = True
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    main()
