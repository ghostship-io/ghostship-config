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

    def test_cooling_zen_is_unavailable_without_removing_source_logins(self):
        source, free = Side(), Side(free=True)
        before = source.records()
        # Captured canonical pool contract: exhausted/cooling routes leave a
        # durable queued job instead of inventing a successful probe result.
        free.call = lambda *args, **kwargs: json.dumps({'job': {
            'id': 'public-probe', 'status': 'queued', 'result': {
                'attempts': [], 'reason': 'all eligible routes unavailable; retry drain after cooldown'}}})
        result = auth.migrate(source, free, self.manifest, PLAN)
        self.assertEqual(result['phase'], 'unavailable')
        self.assertTrue(result['source_login_preserved'])
        self.assertEqual(source.records(), before)
        self.assertEqual(source.events, [])
        self.assertNotEqual(json.loads(self.manifest.read_text())['phase'], 'complete')
        self.assertEqual(auth.migrate(source, free, self.manifest, PLAN), result)
        free.call = Side(free=True).call
        self.assertEqual(auth.migrate(source, free, self.manifest, PLAN)['phase'], 'complete')

    def test_unavailable_probe_exits_the_service_entrypoint_successfully(self):
        import contextlib
        import io
        import os
        source, free = Side(), Side(free=True)
        free.call = lambda *args, **kwargs: json.dumps({'job': {
            'id': 'public-probe', 'status': 'queued', 'result': {
                'reason': 'all eligible routes unavailable; retry drain after cooldown'}}})
        plan = self.manifest.with_name('plan.json')
        plan.write_text(json.dumps(PLAN))
        output = io.StringIO()
        previous_umask = os.umask(0o077)
        try:
            with patch.object(auth, 'Target', side_effect=[source, free]), patch('sys.argv', [
                    'auth', '--podman', 'podman', '--manifest', str(self.manifest), '--plan', str(plan)]), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(auth.main(), 0)
        finally:
            os.umask(previous_umask)
        self.assertEqual(json.loads(output.getvalue())['phase'], 'unavailable')
        self.assertEqual(len(source.records()), 2)

    def test_malformed_or_unexplained_queued_probe_is_not_unavailable(self):
        for raw in ('not JSON', json.dumps({'job': {'id':'public-probe', 'status':'queued'}})):
            with self.subTest(raw=raw):
                source, free = Side(), Side(free=True)
                free.call = lambda *args, **kwargs: raw
                with self.assertRaises(auth.MigrationError):
                    auth.migrate(source, free, self.manifest, PLAN)
                self.assertEqual(len(source.records()), 2)

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

    def test_task_uses_published_runtime_when_image_path_has_no_agent(self):
        source, free = Side(), Side(free=True)
        call = free.call

        def published_only(command, **kwargs):
            # Stable images contain /bin tools but agent is hot-published
            # separately. A bare command fails before the pool can run.
            if command[0] == 'agent':
                return ''
            if command[0] != '/run/ghostship-runtime/current/bin/agent':
                self.fail('task did not use the managed worker runtime')
            return call(command, **kwargs)

        free.call = published_only
        receipt = auth.migrate(source, free, self.manifest, PLAN)
        self.assertEqual(receipt['zen_worker'], 'answered')
        self.assertEqual(free.tasks, 1)

    def test_an_unexpected_free_login_is_not_overwritten(self):
        source, free = Side(), Side(free=True)
        free.rows = [record('other', True)]
        with self.assertRaisesRegex(auth.MigrationError, 'unexpected_login'):
            auth.migrate(source, free, self.manifest, PLAN)
        self.assertEqual(free.events, [])
        self.assertEqual(source.events, [])

    def test_paid_credentials_on_the_free_side_refuse_the_cutover(self):
        source, free = Side(), Side(free=True)
        paid = record('paid', True)
        paid['integrationID'] = 'opencode-go'
        free.rows = [paid]
        with self.assertRaisesRegex(auth.MigrationError, 'free_runtime_contains_paid_credentials'):
            auth.migrate(source, free, self.manifest, PLAN)
        self.assertEqual(free.tasks, 0)
        self.assertEqual(source.events, [])

    def test_native_auth_import_puts_values_on_stdin_never_the_command_line(self):
        target = auth.Target('/podman', 'worker-fixture', '1234:1234', '/home/worker')
        secret_input = json.dumps([record('zen', True)])
        with patch.object(auth.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')) as run:
            target.native(['auth', 'import'], data=secret_input)
        self.assertEqual(run.call_args.kwargs['input'], secret_input)
        self.assertNotIn('synthetic-access', json.dumps(run.call_args.args[0]))

    def test_free_auth_inventory_can_detect_a_credential_for_a_hidden_integration(self):
        target = auth.Target('/podman', 'ghostship-worker', '1234:1234', '/home/worker')
        paid = record('paid', True)
        paid['integrationID'] = 'opencode-go'
        rows = [record('zen', True), paid]
        def exported(command):
            if command == ['auth', 'export']:
                return json.dumps(rows)
            raise auth.MigrationError('native_auth_command_failed')  # unknown integration
        with patch.object(target, 'native', side_effect=exported):
            self.assertEqual(target.records('opencode-go'), [paid])
            self.assertEqual(target.records(), [rows[0]])

    def test_an_auth_error_is_not_misreported_as_exhausted_allowance(self):
        with self.assertRaisesRegex(auth.MigrationError, 'requires_sign_in'):
            auth.quota_or_answer('API key has expired; monthly quota state unavailable')
        self.assertEqual(auth.quota_or_answer('Monthly usage limit reached'), 'quota')

    def test_workspace_roles_and_negative_model_check_use_exact_provider_prefixes(self):
        self.assertEqual(auth.identified({PLAN['go_model']}, PLAN['free_model']), 'go')
        self.assertEqual(auth.identified({PLAN['free_model']}, PLAN['free_model']), 'zen')
        self.assertEqual(auth.model_ids('Models\n\x1b[32mopencode/fixture-free\x1b[0m\n'), {PLAN['free_model']})
