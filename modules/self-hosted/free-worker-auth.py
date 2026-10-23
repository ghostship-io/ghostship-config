#!/usr/bin/env python3
"""Move Console OAuth roles with native OpenCode commands, never auth-file copies.

Run as the host deployment service. Credentials travel only through captured
stdout/stdin. Receipts contain roles and result classes, never credential values.
The private manifest records credential identifiers so retries resume safely.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

PUBLIC_TASK = ('SENSITIVITY: public\nWrite a short public reference paragraph explaining when an HTTP GET '
               'request can be retried safely. Include one concrete example. Use no tools or private information.')


class MigrationError(RuntimeError):
    pass


class Target:
    def __init__(self, podman, container, user, home, *, isolated=False):
        self.podman, self.container, self.user, self.home = podman, container, user, home
        self.isolated = isolated

    def call(self, command, *, data=None, timeout=45, allow_failure=False, stderr=False):
        argv = [self.podman, 'exec', '--interactive', '--user', self.user, '--workdir', '/tmp']
        variables = {'HOME': self.home, 'XDG_CONFIG_HOME': self.home + '/.config',
                     'XDG_DATA_HOME': self.home + '/.local/share', 'XDG_CACHE_HOME': self.home + '/.cache',
                     'XDG_STATE_HOME': self.home + '/.local/state',
                     'OPENCODE_API_KEY': '', 'OPENCODE_GO_API_KEY': '',
                     'OPENCODE_DISABLE_FREE_MODELS': '0' if self.isolated or self.container == 'ghostship-worker' else '1'}
        if self.isolated:
            variables['OPENCODE_CONFIG_CONTENT'] = json.dumps({
                'enabled_providers': ['opencode', 'opencode-go'], 'permission': {'*': 'deny'}, 'mcp': {}})
        for key, value in variables.items():
            argv += ['--env', key + '=' + value]
        argv += [self.container, *(['env', '-u', 'OPENCODE_MODELS_PATH'] if self.isolated else []), *command]
        try:
            result = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            raise MigrationError('native_auth_command_unavailable') from None
        if (result.returncode != 0 and not allow_failure) or len(result.stdout) + len(result.stderr) > 4 * 1024 * 1024:
            raise MigrationError('native_auth_command_failed')
        return result.stdout + ('\n' + result.stderr if stderr else '')

    def native(self, command, *, data=None, timeout=45, **kwargs):
        return self.call(['opencode', *command, *(['--standalone'] if self.isolated else [])],
                         data=data, timeout=timeout, **kwargs)

    def records(self, integration='opencode'):
        try:
            # Go is deliberately absent from the free runtime's integrations.
            # A filtered export resolves that disabled integration and fails;
            # audit this dedicated store without resolving a provider first.
            command = ['auth', 'export']
            if self.container != 'ghostship-worker':
                command.append(integration)
            rows = json.loads(self.native(command))
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError
            return [row for row in rows if row.get('integrationID') == integration]
        except (ValueError, TypeError):
            raise MigrationError('native_auth_export_invalid') from None

    def models(self):
        return model_ids(self.native(['models']))


def model_ids(output):
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', output)
    return {line.strip() for line in clean.splitlines()
            if re.fullmatch(r'[a-z0-9-]+/[^\s]+', line.strip())}


def oauth_rows(rows):
    return [row for row in rows if row.get('integrationID') == 'opencode'
            and (row.get('value') or {}).get('type') == 'oauth']


def identified(models, free_model):
    if any(model.startswith('opencode-go/') for model in models):
        return 'go'
    if free_model in models:
        return 'zen'
    raise MigrationError('console_workspace_role_unknown')


def discover_roles(source, rows, free_model):
    """A private native client discovers what each workspace actually enables."""
    roles = {}
    for row in oauth_rows(rows):
        directory = source.call(['mktemp', '-d', '/tmp/free-auth-role.XXXXXXXX']).strip()
        if not re.fullmatch(r'/tmp/free-auth-role\.[A-Za-z0-9]+', directory):
            raise MigrationError('private_auth_directory_invalid')
        target = Target(source.podman, source.container, source.user, directory, isolated=True)
        try:
            value = copy.deepcopy(row)
            value['active'] = True
            target.native(['auth', 'import'], data=json.dumps([value]))
            role = identified(target.models(), free_model)
            if role in roles or not isinstance(row.get('id'), str):
                raise MigrationError('console_workspace_roles_ambiguous')
            roles[role] = row['id']
        finally:
            source.call(['rm', '-rf', '--', directory])
    if set(roles) != {'go', 'zen'}:
        raise MigrationError('both_console_oauth_logins_required')
    return roles


def write_private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.auth-role-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def active_oauth(rows, expected):
    oauth = oauth_rows(rows)
    return len(oauth) == 1 and oauth[0].get('id') == expected and oauth[0].get('active') is True


def quota_or_answer(output):
    lower = output.lower()
    if any(text in lower for text in ('unauthorized', 'authentication failed', 'api key has expired',
                                      'invalid api key', 'invalid_grant', 'reconnect opencode console')):
        raise MigrationError('go_login_requires_sign_in')
    if any(text in lower for text in ('quota', 'usage limit', 'monthly limit', 'limit reached', 'allowance exhausted')):
        return 'quota'
    for line in output.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('type') == 'text' and (row.get('part') or {}).get('text', '').strip():
            return 'answered'
    raise MigrationError('go_login_probe_unverified')


def migrate(source, free, manifest_path, plan):
    source_rows = source.records()
    if free.records('opencode-go'):
        raise MigrationError('free_runtime_contains_paid_credentials')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('version') != 1 or set(manifest.get('roles', {})) != {'go', 'zen'}:
            raise MigrationError('auth_role_manifest_invalid')
    else:
        manifest = {'version': 1, 'roles': discover_roles(source, source_rows, plan['free_model']), 'phase': 'identified'}
        write_private(manifest_path, manifest)
    go, zen = manifest['roles']['go'], manifest['roles']['zen']
    free_rows = free.records()
    if not active_oauth(free_rows, zen):
        if oauth_rows(free_rows):
            raise MigrationError('free_runtime_has_an_unexpected_login')
        row = next((row for row in oauth_rows(source_rows) if row.get('id') == zen), None)
        if row is None:
            raise MigrationError('zen_login_missing_on_both_sides')
        row = copy.deepcopy(row)
        row['active'] = True
        free.native(['auth', 'import'], data=json.dumps([row]))
        if not active_oauth(free.records(), zen):
            raise MigrationError('zen_login_import_unverified')
        manifest['phase'] = 'imported'
        write_private(manifest_path, manifest)
    models = free.models()
    if plan['free_model'] not in models or any(model.startswith('opencode-go/') for model in models):
        raise MigrationError('free_model_scope_invalid')
    if manifest.get('phase') != 'complete':
        # The native login must prove itself through the real bounded worker
        # before the source login is removed. A stable key makes retries safe.
        # Code is published independently of the stable image, whose /bin
        # intentionally contains no agent launcher. Use its atomic runtime link.
        raw = free.call(['/run/ghostship-runtime/current/bin/agent', 'free-inference', 'run', '--profile', 'research', '--sensitivity', 'public',
                         '--provider', 'opencode', '--request-key', plan['probe_key'],
                         '--prompt', PUBLIC_TASK], timeout=240, allow_failure=True)
        try:
            result = json.loads(raw)
            job = result['job']
        except (ValueError, KeyError, TypeError):
            raise MigrationError('zen_worker_probe_invalid') from None
        if job.get('status') != 'succeeded':
            raise MigrationError('zen_worker_probe_failed_source_login_preserved')
        manifest['public_job'] = job['id']
        manifest['zen_worker'] = 'answered'
        write_private(manifest_path, manifest)
    if not any(row.get('id') == go for row in oauth_rows(source_rows)):
        raise MigrationError('go_login_missing_from_t3')
    source.native(['auth', 'switch', 'opencode', go])
    if any(row.get('id') == zen for row in oauth_rows(source.records())):
        source.native(['auth', 'logout', 'opencode', zen])
    # The expired legacy Go key is not part of the OAuth subscription route.
    for row in source.records('opencode-go'):
        if (row.get('value') or {}).get('type') == 'key':
            source.native(['auth', 'logout', 'opencode-go', row['id']])
    if not active_oauth(source.records(), go) or not active_oauth(free.records(), zen):
        raise MigrationError('oauth_role_separation_unverified')
    models = source.models()
    if any(model.startswith('opencode/') for model in models) or not any(model.startswith('opencode-go/') for model in models):
        raise MigrationError('t3_model_scope_invalid')
    if manifest.get('phase') != 'complete':
        result = source.native(['run', '--model', plan['go_model'], '--format', 'json',
                                'Public authentication probe. Reply with exactly OK. Do not use tools.'],
                               timeout=90, allow_failure=True, stderr=True)
        manifest['go_login'] = quota_or_answer(result)
    manifest['phase'] = 'complete'
    write_private(manifest_path, manifest)
    return {'phase': 'complete', 'zen_worker': manifest['zen_worker'], 'go_login': manifest['go_login'],
            't3_zen_models': False, 'free_go_models': False, 'separate_oauth_stores': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--podman', required=True)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    source = Target(args.podman, 't3code', '3000:3000', '/home/t3code')
    free = Target(args.podman, 'ghostship-worker', '63000:62020', '/home/worker')
    try:
        plan = json.loads(args.plan.read_text())
        if (set(plan) != {'free_model', 'go_model', 'probe_key'} or not plan['free_model'].startswith('opencode/') or
                not plan['go_model'].startswith('opencode-go/') or
                not re.fullmatch(r'[a-z0-9._-]{1,128}', plan['probe_key'])):
            raise MigrationError('auth_role_plan_invalid')
        result = migrate(source, free, args.manifest, plan)
    except (MigrationError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'phase': 'blocked', 'reason': str(exc) if isinstance(exc, MigrationError) else 'auth_role_state_invalid'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
