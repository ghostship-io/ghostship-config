"""Slow main coverage must not consume the fast PR gate runner pool."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CISchedulingTests(unittest.TestCase):
    def test_fast_push_lane_cancels_superseded_main_without_launching_integration(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn("github.event_name == 'push' && 'main'", text)
        self.assertIn('cancel-in-progress: true', text)
        self.assertNotIn('|| github.sha', text)
        self.assertIn("- cron: '17 5 * * *'", text)
        self.assertIn("if: github.event_name == 'pull_request' || github.event_name == 'push'", text)
        for name in ('Validate container development workflow', 'Evaluate hosts and run regression tests'):
            step = text.split('- name: ' + name, 1)[1].split('- name:', 1)[0]
            self.assertIn("if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'", step)
        self.assertIn('gitleaks dir --redact --no-banner .', text)
        scan = text.split('- name: Scan current source for secrets', 1)[1]
        self.assertNotIn('if:', scan)
        self.assertIn('.#checks.x86_64-linux.host-evaluation', text)
        self.assertIn('scripts/check', text)

    def test_fast_and_integration_entrypoints_retain_their_coverage(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        fast = (ROOT / 'scripts/check').read_text()
        integration = (ROOT / 'scripts/check-integration').read_text()
        self.assertIn('-c scripts/check\n', text)
        self.assertIn('-c scripts/check-integration\n', text)
        self.assertIn('scripts/check-unit.py', fast)
        self.assertIn('gitleaks dir --redact --no-banner .', fast)
        self.assertNotIn('nix eval', fast)
        self.assertIn('nixosConfigurations.$host.config.system.build.toplevel.drvPath', integration)
        self.assertIn('tests/apparmor-public.nix', integration)

    def test_browser_integration_is_nightly_or_manual_without_pr_push_triggers(self):
        text = (ROOT / '.github/workflows/t3code.yml').read_text()
        triggers = text.split('permissions:', 1)[0]
        self.assertNotIn('push:', triggers)
        self.assertNotIn('pull_request:', triggers)
        self.assertIn('schedule:', triggers)
        self.assertIn('workflow_dispatch:', triggers)
        self.assertIn('cancel-in-progress: true', text)
        self.assertIn('tests/t3code-pwa.browser.cjs', text)
