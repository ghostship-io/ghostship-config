"""Slow main coverage must not consume the fast PR gate runner pool."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CISchedulingTests(unittest.TestCase):
    def test_pr_lane_has_no_duplicate_main_or_scheduled_runs(self):
        text = (ROOT / '.github/workflows/ci.yml').read_text()
        self.assertNotIn('  push:', text)
        self.assertIn('cancel-in-progress: true', text)
        self.assertNotIn('|| github.sha', text)
        self.assertNotIn('schedule:', text)
        self.assertIn('runs-on: [self-hosted, Linux, ARM64, ghostship-fast]', text)
        self.assertIn('timeout-minutes: 2', text)
        checkout = text.split('  integration:', 1)[0]
        self.assertIn('filter: blob:none', checkout)
        self.assertIn('fetch-depth: 0', checkout)
        self.assertIn("if: github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name == github.repository", text)
        for name in ('Validate container development workflow', 'Evaluate hosts and run regression tests'):
            step = text.split('- name: ' + name, 1)[1].split('- name:', 1)[0]
            self.assertNotIn('if:', step)
        self.assertIn("if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'", text)
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

    def test_browser_integration_is_manual_without_pr_push_triggers(self):
        text = (ROOT / '.github/workflows/t3code.yml').read_text()
        triggers = text.split('permissions:', 1)[0]
        self.assertNotIn('push:', triggers)
        self.assertNotIn('pull_request:', triggers)
        self.assertNotIn('schedule:', triggers)
        self.assertIn('workflow_dispatch:', triggers)
        self.assertIn('cancel-in-progress: true', text)
        self.assertIn('tests/t3code-pwa.browser.cjs', text)
