"""The free worker must never inherit subscription or unrelated credentials."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'modules/self-hosted/free-worker-credentials.py'
spec = importlib.util.spec_from_file_location('free_worker_credentials', SOURCE)
credentials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credentials)


class ProjectionTests(unittest.TestCase):
    def test_projection_contains_only_declared_free_provider_variables(self):
        source = ('OPENCODE_GO_API_KEY=fixture-paid\nOPENCODE_API_KEY=fixture-console\n'
                  'OTHER_PASSWORD=fixture-unrelated\nGROQ_API_KEY=old\n'
                  'export GROQ_API_KEY="fixture with spaces"\n')
        self.assertEqual(credentials.select(source, ['GROQ_API_KEY']),
                         'GROQ_API_KEY="fixture with spaces"\n')

    def test_console_and_subscription_keys_cannot_be_requested(self):
        for name in credentials.FORBIDDEN:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'forbidden'):
                credentials.select(name + '=fixture\n', [name])

    def test_atomic_rotation_keeps_only_the_new_private_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'credentials.env'
            destination.write_text('OLD=fixture\n')
            credentials.write(destination, 'GROQ_API_KEY=fixture\n', os.getuid(), os.getgid())
            self.assertEqual(destination.read_text(), 'GROQ_API_KEY=fixture\n')
            self.assertEqual(destination.stat().st_mode & 0o777, 0o400)
            self.assertEqual(list(Path(directory).iterdir()), [destination])
