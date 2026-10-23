"""Agent releases and dashboard edits must not rebuild or restart base images."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = load('runtime_publish', 'modules/self-hosted/container-runtime-publish.py')
impact = load('restart_impact', 'scripts/check-container-restarts.py')


class RuntimePublication(unittest.TestCase):
    def test_atomic_publication_and_retry_do_not_loop_unchanged_code(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(publisher.publish(directory, '/nix/store/runtime-one'))
            self.assertFalse(publisher.publish(directory, '/nix/store/runtime-one'))
            self.assertTrue(publisher.publish(directory, '/nix/store/runtime-two'))
            self.assertEqual(os.readlink(Path(directory) / 'current'), '/nix/store/runtime-two')
            self.assertFalse((Path(directory) / 'current.new').exists())

    def test_only_changed_code_restarts_its_active_service(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['publish', '--state', directory, '--runtime', '/nix/store/runtime-one',
                    '--unit', 'podman-fixture.service', '--systemctl', '/systemctl']
            with patch('sys.argv', argv), patch.object(publisher.subprocess, 'run') as run:
                run.return_value.returncode = 0
                publisher.main()
                self.assertEqual(run.call_args.args[0],
                                 ['/systemctl', '--no-block', 'try-restart', 'podman-fixture.service'])
                run.reset_mock()
                publisher.main()
                run.assert_not_called()

    def test_failed_restart_is_retried_after_pointer_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['publish', '--state', directory, '--runtime', '/runtime',
                    '--unit', 'podman-fixture.service', '--systemctl', '/systemctl']
            with patch('sys.argv', argv), patch.object(publisher.subprocess, 'run') as run:
                active = subprocess.CompletedProcess([], 0)
                run.side_effect = [active, subprocess.CalledProcessError(1, 'restart')]
                with self.assertRaises(subprocess.CalledProcessError):
                    publisher.main()
                self.assertEqual(os.readlink(Path(directory) / 'current'), '/runtime')
                run.side_effect = [active, active]
                publisher.main()
                self.assertEqual(run.call_count, 4)

    def test_queued_publication_does_not_start_a_stopped_container(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('sys.argv', ['publish', '--state', directory, '--runtime', '/runtime',
                                    '--unit', 'podman-fixture.service', '--systemctl', '/systemctl']), \
                 patch.object(publisher.subprocess, 'run') as run:
                run.return_value.returncode = 3
                publisher.main()
                self.assertEqual(run.call_count, 1)


class RestartImpact(unittest.TestCase):
    def test_reports_direct_and_dependency_restarts_but_not_dashboard_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = Path(directory) / 'old', Path(directory) / 'new'
            old.mkdir(); new.mkdir()
            for root, version in [(old, 'one'), (new, 'two')]:
                (root / 'dashboard.service').write_text(version)
                (root / 'required.service').write_text(version)
                (root / 'apparmor.service').write_text('X-ReloadIfChanged=true\n' + version)
                (root / 'podman-homepage.service').write_text('Wants=dashboard.service\nAfter=dashboard.service\n')
                (root / 'podman-cloudflared.service').write_text('Requires=apparmor.service\n')
                (root / 'podman-fixture.service').write_text('Requires=required.service\n')
                (root / 'podman-own.service').write_text(version)
            result = {name: reasons for name, reasons, _ in impact.report(old, new)}
            self.assertEqual(result['podman-homepage.service'], [])
            self.assertEqual(result['podman-cloudflared.service'], [])
            self.assertEqual(result['podman-fixture.service'], ['dependency: required.service'])
            self.assertEqual(result['podman-own.service'], ['unit changed'])

    def test_whole_agent_source_and_dashboard_helpers_are_rejected_podman_is_allowed(self):
        self.assertEqual(impact.shared_triggers('PATH=/nix/store/' + 'a' * 32 + '-podman-5/bin'), [])
        self.assertEqual(impact.shared_triggers('/nix/store/' + 'a' * 32 + '-source/tools/python'), ['whole agent source'])
        self.assertEqual(impact.shared_triggers('ghostship-config set /srv/apps/fixture'), [])
        self.assertIn('dashboard reconciliation inside container unit',
                      impact.shared_triggers('ghostship-dashboard-sync'))

    def test_dashboard_code_is_outside_container_startup(self):
        for module in ['homepage', 'muximux', 'app-registry']:
            text = (ROOT / f'modules/self-hosted/{module}.nix').read_text()
            self.assertNotIn('systemd.services.podman-homepage.preStart', text)
            self.assertNotIn('systemd.services.podman-muximux.preStart', text)
        text = (ROOT / 'modules/self-hosted/app-registry.nix').read_text()
        self.assertIn('systemd.services.ghostship-homepage-config.script', text)
        self.assertIn('systemd.services.ghostship-muximux-config.script', text)


class BaseImageContract(unittest.TestCase):
    def test_service_images_are_local_base_images_without_agent_packages(self):
        text = (ROOT / 'modules/self-hosted/service-base-image.nix').read_text()
        self.assertNotIn('agent', text[text.index('{ pkgs,'):])
        for module in ['github-engineering', 'private-integrations']:
            text = (ROOT / f'modules/self-hosted/{module}.nix').read_text()
            self.assertIn('import ./service-base-image.nix', text)
            self.assertNotIn('mkPrivateIntegrations', text)
            self.assertNotIn('privateAddons.image', text)
