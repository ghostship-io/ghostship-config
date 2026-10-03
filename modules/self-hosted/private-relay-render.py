"""Render runtime-only relay files from existing scoped secret projections."""
import grp
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path('/run/ghostship-integrations')


def values(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        key, separator, value = line.partition('=')
        if separator:
            parts = shlex.split(value)
            result[key] = parts[0] if len(parts) == 1 else ''
    return result


def write(name, content):
    fd, temporary = tempfile.mkstemp(dir=ROOT, prefix='.' + name)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, 62020, grp.getgrnam('ghostship-mcp').gr_gid)
        os.chmod(temporary, 0o400)
        os.replace(temporary, ROOT / name)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    profiles = dict(zip(('keep', 'amazon'), map(values, sys.argv[1:3])))
    # Validate everything before replacing any live credential/configuration.
    for profile, fields in profiles.items():
        if not re.fullmatch(r'tunnel_[a-f0-9]{32}', fields.get('TUNNEL_ID', '')) or not fields.get('API_KEY'):
            raise SystemExit(f'{profile}: owner-provisioned tunnel ID/runtime key missing')
    if profiles['keep']['TUNNEL_ID'] == profiles['amazon']['TUNNEL_ID']:
        raise SystemExit('Profiles require distinct tunnel IDs')
    for index, (profile, fields) in enumerate(profiles.items()):
        write(profile + '.key', fields['API_KEY'])
        write(profile + '.yaml', json.dumps({
            'config_version': 1,
            'control_plane': {'base_url': 'https://api.openai.com', 'tunnel_id': fields['TUNNEL_ID'],
                              'api_key': 'file:' + str(ROOT / (profile + '.key'))},
            'health': {'listen_addr': f'127.0.0.1:{8081 + index}'},
            'process': {'pid_file': '/tmp/' + profile + '.pid'},
            'log': {'level': 'warn', 'format': 'json'},
            'mcp': {'commands': [{'channel': 'main', 'command': sys.argv[3] + ' ' + profile}]},
        }))
    # Personal destination belongs to deployment, never to the reusable image.
    write('runtime.json', json.dumps({'home_postal_code': 'a postal code'}))


if __name__ == '__main__':
    main()
