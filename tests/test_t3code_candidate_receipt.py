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
                'app_ready', 'provider_turn', 'agent_cli', 'skills', 'desktop_transport')},
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

    def test_immediate_restart_names_the_exact_missing_candidate_receipt(self):
        with patch.object(deployer.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, str(self.path)):
                deployer.force_restart('systemctl', 'podman',
                    self.root/'ledger', 'journal', None, self.root, self.archive,
                    candidate_acceptor=lambda *_: deployer.require_candidate(self.root, self.archive, 'podman'))
        run.assert_not_called()

    def test_immediate_restart_is_effective_and_receipt_is_checked(self):
        self.verify()
        argv = ['deployer', '--force',
            '--state-dir', str(self.root), '--image-archive', str(self.archive),
            '--restart-ledger', str(self.root/'ledger'), '--audit-log', str(self.root/'audit')]
        with patch.object(sys, 'argv', argv), patch.object(deployer, 'produce_candidate_receipt', return_value=None), patch.object(deployer.subprocess, 'run',
                return_value=Mock(returncode=0)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(deployer.main(), 0)
        self.assertEqual(json.loads((self.root/'ledger').read_text())['mode'], 'candidate-accepted')

    def test_missing_candidate_receipt_prevents_restart(self):
        with patch.object(deployer.subprocess, 'run',
                return_value=Mock(returncode=0, stdout='active')) as run:
            with self.assertRaisesRegex(RuntimeError, str(self.path)):
                deployer.run_deployment(self.root, self.root, image_archive=self.archive,
                    deployment_reader=lambda: 'old-definition', tool_lock_acquirer=lambda: None,
                    candidate_acceptor=lambda *_: deployer.require_candidate(self.root, self.archive, 'podman'))
        run.assert_not_called()

    def test_candidate_acceptance_receipt_must_match_target_image_and_deployment(self):
        self.path.write_text(json.dumps(self.receipt))
        accepted = deployer.verify_candidate_receipt(self.root, self.archive,
                                                       'candidate-definition')
        self.assertTrue(accepted['verified'])
        for field, wrong in (('deployment_id', 'other'), ('image_id', 'other')):
            with self.subTest(field=field):
                broken = dict(self.receipt, **{field: wrong})
                self.path.write_text(json.dumps(broken))
                with self.assertRaises(RuntimeError):
                    deployer.verify_candidate_receipt(self.root, self.archive,
                                                       'candidate-definition')

    def test_candidate_acceptance_refuses_missing_or_failed_receipt(self):
        with self.assertRaises(RuntimeError):
            deployer.verify_candidate_receipt(self.root, self.archive,
                                               'candidate-definition')
        self.receipt['checks']['provider_turn'] = False
        self.path.write_text(json.dumps(self.receipt))
        with self.assertRaises(RuntimeError):
            deployer.verify_candidate_receipt(self.root, self.archive,
                                               'candidate-definition')

    def test_acceptance_receipt_allows_immediate_pickup(self):
        (self.root / 'desired').write_text('candidate-definition')
        (self.root / 'applied').write_text('old-definition')
        def accept(*_args):
            self.path.write_text(json.dumps(self.receipt))
        with patch.object(deployer.subprocess, 'run',
                side_effect=[Mock(returncode=0, stdout='active'), Mock(returncode=0)]) as run:
            result = deployer.run_deployment(
                self.root, self.root, image_archive=self.archive,
                deployment_reader=lambda: 'old-definition', tool_lock_acquirer=lambda: None,
                candidate_acceptor=accept, healthy_waiter=lambda: True,
            )
        self.assertEqual(result, 0)
        self.assertTrue(any(call.args[0][-2:] == ['restart', 'podman-t3code.service']
                            for call in run.call_args_list))

    def test_same_image_restart_needs_no_migration_receipt(self):
        with patch.object(deployer, 'container_identity', return_value={
                'image': 'sha256:'+self.image, 'deployment': 'candidate-definition'}):
            deployer.require_candidate(self.root, self.archive, 'podman')

    def test_secret_inode_change_restarts_after_candidate_acceptance(self):
        (self.root / 'desired').write_text('candidate-definition')
        (self.root / 'applied').write_text('candidate-definition')
        (self.root / 'desired-inputs').write_text('agent=pin secret_inode=changed\n')
        def accept(*_args):
            self.path.write_text(json.dumps(self.receipt))
        with patch.object(deployer.subprocess, 'run',
                side_effect=[Mock(returncode=0, stdout='active'), Mock(returncode=0)]) as run:
            result = deployer.run_deployment(
                self.root, self.root, image_archive=self.archive,
                deployment_reader=lambda: 'candidate-definition', tool_lock_acquirer=lambda: None,
                candidate_acceptor=accept, healthy_waiter=lambda: True,
            )
        self.assertEqual(result, 0)
        self.assertEqual((self.root / 'applied-inputs').read_text(), 'agent=pin secret_inode=changed\n')
        self.assertTrue(any(call.args[0][-2:] == ['restart', 'podman-t3code.service']
                            for call in run.call_args_list))

    def test_same_image_with_stale_secret_inode_is_not_adopted(self):
        secret = self.root / 'provider.env'
        secret.write_text('OPENROUTER_API_KEY=fixture\n')
        with patch.object(deployer, 'container_identity', return_value={
                'image': 'sha256:'+self.image, 'deployment': 'candidate-definition'}), \
             patch.object(deployer, 'live_inputs_match', return_value=False):
            with self.assertRaisesRegex(RuntimeError, str(self.path)):
                deployer.require_candidate(self.root, self.archive, 'podman',
                                           provider_secrets_file=secret)

    def test_deployed_inputs_receipt_records_the_pinned_agent_and_live_secret_inode(self):
        secret = self.root / 'provider.env'
        secret.write_text('OPENROUTER_API_KEY=fixture\n')
        tooling = self.root / 'pinned-agent-tools'
        with patch.object(deployer, 'live_agent_path', return_value=str(tooling.resolve())), \
             patch.object(deployer, 'live_secret_inode', return_value=str(secret.stat().st_ino)):
            deployer.write_live_inputs_receipt(
                self.root, 'podman', 'candidate-definition', 'pinned-revision', tooling, secret
            )
        receipt = json.loads((self.root / 'deployed-inputs.json').read_text())
        self.assertEqual(receipt['deployment_id'], 'candidate-definition')
        self.assertEqual(receipt['agent_revision'], 'pinned-revision')
        self.assertEqual(receipt['agent_path'], str(tooling.resolve()))
        self.assertEqual(receipt['provider_secret_inode'], str(secret.stat().st_ino))
        self.assertTrue(receipt['verified'])
