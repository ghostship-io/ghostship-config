"""Collector entrypoint fixtures never inherit a host runtime file."""
from pathlib import Path


def state_args(root, args):
    options = ('output', 'state', 'window-state', 'events-cache', 'facts', 'aa-catalog',
               'aa-cache', 'aa-3d-cache', 'snapshot', 'delegation-ledger',
               'delegation-backfill', 'custom-resets', 'announced-resets', 'picker-state')
    defaults = [value for option in options
                for value in ('--' + option, str(Path(root) / (option + '.json')))]
    return defaults + args
