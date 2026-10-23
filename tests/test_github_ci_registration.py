"""Registration must keep the administration PAT out of child argv/env and state."""
from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'ci_registration', ROOT / 'modules/self-hosted/github-ci-register.py')
registration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registration)


class RegistrationTests(unittest.TestCase):
    def test_only_one_use_token_reaches_unprivileged_configure_and_no_pat_is_copied(self):
        pat, token = 'fixture-administration-credential', 'fixture-one-use-registration'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, work, logs = (root / name for name in ('state', 'work', 'logs'))
            for path in (state, work, logs):
                path.mkdir()
            (state / '.current-token').write_text('stale credential')
            (work / 'old-checkout').mkdir()
            (logs / 'previous.log').write_text('retained')
            credential = root / 'credential'
            credential.write_text(pat)
            args = SimpleNamespace(state_dir=str(state), work_dir=str(work), logs_dir=str(logs),
                                   token_file=str(credential), repository='fixture/repository',
                                   runner='/fixture/Runner.Listener', name='fixture', label='fixture')
            owner = state.stat()
            def api(request, timeout):
                self.assertEqual(request.full_url,
                                 'https://api.github.com/repos/fixture/repository/actions/runners/registration-token')
                self.assertEqual(request.get_method(), 'POST')
                self.assertEqual(request.get_header('Authorization'), 'Bearer ' + pat)
                return io.BytesIO(json.dumps({'token': token}).encode())

            def configure(argv, **kwargs):
                self.assertNotIn(pat, json.dumps([argv, kwargs['env']]))
                self.assertNotIn(token, json.dumps(argv))
                self.assertNotIn('--pat', argv)
                self.assertNotIn('--token', argv)
                self.assertEqual(kwargs['env']['ACTIONS_RUNNER_INPUT_TOKEN'], token)
                self.assertNotIn('ACTIONS_RUNNER_INPUT_PAT', kwargs['env'])
                self.assertNotIn('GITHUB_TOKEN', kwargs['env'])
                self.assertNotIn('user', kwargs)  # inherits systemd's dynamic identity
                self.assertTrue(kwargs['capture_output'])
                self.assertFalse((state / '.registration-token').exists())
                self.assertFalse((state / '.current-token').exists())
                self.assertFalse((work / 'old-checkout').exists())
                for name in ('.runner', '.credentials', '.credentials_rsaparams'):
                    (state / name).write_text('runner session credential')

            with patch.object(registration.urllib.request, 'urlopen', side_effect=api), \
                    patch.object(registration.subprocess, 'run', side_effect=configure) as child, \
                    patch.dict(registration.os.environ, {'ACTIONS_RUNNER_INPUT_PAT': pat,
                                                         'GITHUB_TOKEN': pat}):
                registration.prepare(args)
                self.assertEqual((state / '.registration-token').stat().st_mode & 0o777, 0o600)
                self.assertEqual((state / '.registration-token').stat().st_uid, owner.st_uid)
                registration.configure(args)
            child.assert_called_once()
            self.assertEqual((logs / 'previous.log').read_text(), 'retained')
            for name in ('.runner', '.credentials', '.credentials_rsaparams'):
                self.assertEqual((work / name).resolve(), state / name)
            for path in state.rglob('*'):
                if path.is_file():
                    self.assertNotIn(pat, path.read_text())

    def test_errors_never_replay_credentialed_subprocess_output(self):
        secret = 'fixture-credential'
        error = subprocess.CalledProcessError(1, ['configure'], output=secret, stderr=secret)
        output = io.StringIO()
        with patch.object(registration.argparse.ArgumentParser, 'parse_args'), \
                patch.object(registration, 'configure', side_effect=error), redirect_stderr(output):
            self.assertEqual(registration.main(), 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn('CalledProcessError', output.getvalue())

    def test_refuse_root_owned_state_before_contacting_github_or_clearing_state(self):
        args = SimpleNamespace(state_dir='/fixture/state', work_dir='/fixture/work',
                               logs_dir='/fixture/logs', repository='fixture/repository')
        with patch.object(registration.Path, 'stat', return_value=SimpleNamespace(st_uid=0)), \
                patch.object(registration.urllib.request, 'urlopen') as api:
            with self.assertRaises(ValueError):
                registration.prepare(args)
        api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
