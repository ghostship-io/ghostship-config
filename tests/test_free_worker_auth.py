"""OAuth cutover must preserve the source login until the bounded free task works."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PLAN = {'free_model': 'opencode/fixture-free', 'go_model': 'opencode-go/fixture-paid', 'probe_key': 'public-docs-fixture'}
SOURCE = Path(__file__).resolve().parents[1] / 'modules/self-hosted/free-worker-auth.py'
spec = importlib.util.spec_from_file_location('free_worker_auth', SOURCE)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


def record(role, active=False):
    return {'id': role + '-credential', 'integrationID': 'opencode', 'active': active,
            'value': {'type': 'oauth', 'access': 'synthetic-access'}}


class Side:
    def __init__(self, free=False, success=True):
        self.free, self.success = free, success
        self.rows = [] if free else [record('go'), record('zen', True)]
        self.events = []
        self.tasks = 0

    def records(self, integration='opencode'):
        return copy.deepcopy([row for row in self.rows if row['integrationID'] == integration])

    def native(self, command, **kwargs):
        self.events.append(command)
        if command[:2] == ['auth', 'import']:
            self.rows = json.loads(kwargs['data'])
        elif command[:2] == ['auth', 'switch']:
            for row in self.rows:
                row['active'] = row['id'] == command[-1]
        elif command[:2] == ['auth', 'logout']:
            self.rows = [row for row in self.rows if row['id'] != command[-1]]
        elif command[0] == 'run':
            return 'Monthly usage limit reached'
        return ''

    def models(self):
        return {PLAN['free_model']} if self.free else {PLAN['go_model']}

    def call(self, command, **kwargs):
        self.tasks += 1
        return json.dumps({'job': {'id': 'public-docs-task', 'status': 'succeeded' if self.success else 'failed'}})


class AuthCutoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manifest = Path(self.temp.name) / 'roles.json'
        self.roles = patch.object(auth, 'discover_roles', return_value={'go': 'go-credential', 'zen': 'zen-credential'})
        self.roles.start()
        self.addCleanup(self.roles.stop)

    def test_failed_zen_round_leaves_both_source_logins_untouched(self):
        source, free = Side(), Side(free=True, success=False)
        before = source.records()
        with self.assertRaisesRegex(auth.MigrationError, 'source_login_preserved'):
            auth.migrate(source, free, self.manifest, PLAN)
        self.assertEqual(source.records(), before)
        self.assertEqual(source.events, [])

    def test_successful_cutover_is_idempotent_and_does_not_repeat_the_public_task(self):
        source, free = Side(), Side(free=True)
        receipt = auth.migrate(source, free, self.manifest, PLAN)
        self.assertTrue(receipt['separate_oauth_stores'])
        self.assertEqual(receipt['go_login'], 'quota')
        self.assertEqual([row['id'] for row in source.records()], ['go-credential'])
        self.assertEqual([row['id'] for row in free.records()], ['zen-credential'])
        self.assertEqual(auth.migrate(source, free, self.manifest, PLAN), receipt)
        self.assertEqual(free.tasks, 1)
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('synthetic-access', self.manifest.read_text())

    def test_an_unexpected_free_login_is_not_overwritten(self):
        source, free = Side(), Side(free=True)
        free.rows = [record('other', True)]
        with self.assertRaisesRegex(auth.MigrationError, 'unexpected_login'):
            auth.migrate(source, free, self.manifest, PLAN)
        self.assertEqual(free.events, [])
        self.assertEqual(source.events, [])

    def test_native_auth_import_puts_values_on_stdin_never_the_command_line(self):
        target = auth.Target('/podman', 'worker-fixture', '1234:1234', '/home/worker')
        secret_input = json.dumps([record('zen', True)])
        with patch.object(auth.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')) as run:
            target.native(['auth', 'import'], data=secret_input)
        self.assertEqual(run.call_args.kwargs['input'], secret_input)
        self.assertNotIn('synthetic-access', json.dumps(run.call_args.args[0]))

    def test_an_auth_error_is_not_misreported_as_exhausted_allowance(self):
        with self.assertRaisesRegex(auth.MigrationError, 'requires_sign_in'):
            auth.quota_or_answer('API key has expired; monthly quota state unavailable')
        self.assertEqual(auth.quota_or_answer('Monthly usage limit reached'), 'quota')

    def test_workspace_roles_and_negative_model_check_use_exact_provider_prefixes(self):
        self.assertEqual(auth.identified({PLAN['go_model']}, PLAN['free_model']), 'go')
        self.assertEqual(auth.identified({PLAN['free_model']}, PLAN['free_model']), 'zen')
        self.assertEqual(auth.model_ids('Models\n\x1b[32mopencode/fixture-free\x1b[0m\n'), {PLAN['free_model']})
