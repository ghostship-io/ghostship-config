"""The exact image needs all candidate checks, even for an owner-forced swap."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
spec = importlib.util.spec_from_file_location('t3_candidate_deployer',
    Path(__file__).resolve().parents[1] / 'packages/t3code/deploy-when-idle.py')
deployer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployer)


class CandidateReceipt(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / 'image.tar'
        config = b'{"rootfs":{"diff_ids":["candidate-layer"]}}'
        self.image = hashlib.sha256(config).hexdigest()
        with tarfile.open(self.archive, 'w') as archive:
            for name, content in (
                ('manifest.json', b'[{"Config":"config.json"}]'),
                ('config.json', config),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        (self.root / 'desired').write_text('candidate-definition')
        (self.root / 'receipts').mkdir()
        self.path = self.root / 'receipts/candidate-definition.json'
        self.receipt = {
            'deployment_id': 'candidate-definition', 'image_id': self.image,
            'candidate_name': 't3code-candidate-acceptance',
            'live_before': 'preserved-live', 'live_after': 'preserved-live',
            'checks': {name: True for name in (
                'authenticated_app', 'provider_turn', 'agent_cli', 'skills', 'desktop_transport')},
        }
        self.inspect = patch.object(deployer, 'container_identity', return_value={'image': 'old-image'})
        self.inspect.start()
        self.addCleanup(self.inspect.stop)

    def verify(self):
        self.path.write_text(json.dumps(self.receipt))
        deployer.require_candidate(self.root, self.archive, 'podman')

    def test_exact_image_and_all_checks_pass(self):
        self.verify()

    def test_receipt_for_another_image_or_definition_is_refused(self):
        for field in ('image_id', 'deployment_id', 'candidate_name', 'live_after'):
            with self.subTest(field=field), patch.dict(self.receipt, {field: 'wrong'}):
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_each_missing_acceptance_check_is_refused(self):
        for check in self.receipt['checks']:
            with self.subTest(check=check), patch.dict(self.receipt['checks'], {check: False}):
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_owner_force_cannot_bypass_a_missing_receipt(self):
        with patch.object(deployer.subprocess, 'run') as run:
            with self.assertRaises(FileNotFoundError):
                deployer.force_restart('systemctl', 'podman', 'activate reviewed image',
                    self.root/'ledger', 'journal', None, self.root, self.archive)
        run.assert_not_called()

    def test_raw_force_is_effective_and_receipt_is_checked(self):
        self.verify()
        argv = ['deployer', '--force', '--owner-request', 'activate reviewed image',
            '--state-dir', str(self.root), '--image-archive', str(self.archive),
            '--restart-ledger', str(self.root/'ledger'), '--audit-log', str(self.root/'audit')]
        with patch.object(sys, 'argv', argv), patch.object(deployer.subprocess, 'run',
                return_value=Mock(returncode=0)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(deployer.main(), 0)
        self.assertEqual(json.loads((self.root/'ledger').read_text())['mode'], 'forced')

    def test_idle_cannot_bypass_a_missing_receipt(self):
        with patch.object(deployer.subprocess, 'run',
                return_value=Mock(returncode=0, stdout='active')) as run:
            with self.assertRaises(FileNotFoundError):
                deployer.run_deployment(self.root, self.root, image_archive=self.archive,
                    idle_checker=lambda: True, sleep_fn=lambda _: None,
                    deployment_reader=lambda: 'old-definition', tool_lock_acquirer=lambda: None)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [['systemctl', 'is-active', 'podman-t3code.service']])

    def test_same_image_restart_needs_no_migration_receipt(self):
        with patch.object(deployer, 'container_identity', return_value={'image': 'sha256:'+self.image}):
            deployer.require_candidate(self.root, self.archive, 'podman')
