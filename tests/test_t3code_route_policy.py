"""The owner's route policy reaches T3 and covers only approved worker routes."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T3CODE = (ROOT / "modules/self-hosted/t3code.nix").read_text()
APPROVED_FREE = json.loads(
    (ROOT / "modules/self-hosted/ai-usage/approved-free-workers.json").read_text()
)


class T3RoutePolicyTests(unittest.TestCase):
    def test_the_container_reads_the_generated_policy_from_the_config_path(self):
        self.assertIn('GHOSTSHIP_ROUTE_POLICY_PATH = "/etc/ghostship/route-policy.json"', T3CODE)
        self.assertIn('"/etc/ghostship/route-policy.json:/etc/ghostship/route-policy.json:ro"', T3CODE)
        self.assertIn('environment.etc."ghostship/route-policy.json".source = ownerRoutePolicy', T3CODE)

    def test_the_free_allow_list_is_derived_from_the_installed_approved_source(self):
        self.assertIn('approvedFreeWorkers = ./ai-usage/approved-free-workers.json', T3CODE)
        self.assertIn('environment.etc."ghostship/approved-free-workers.json".source = approvedFreeWorkers', T3CODE)
        self.assertIn('model = "${entry.provider}/${entry.model}"', T3CODE)
        self.assertIn('provider = "opencode-free"', T3CODE)
        self.assertIn('}) approvedFreeWorkerRoutes.entries', T3CODE)
        self.assertGreater(len(APPROVED_FREE["entries"]), 0)

    def test_worker_routes_and_all_role_fable_denials_are_explicit(self):
        for route in (
            'model = "gpt-6-luna"',
            'model = "claude-sonnet-5-5"',
            'model = "command-code/deepseek/deepseek-v4.1-flash"',
            'model = "gemini-3.8-flash"',
            'model = "gemini-3.8-flash-high"',
            'model = "gemini-4-argon"',
        ):
            self.assertIn(route, T3CODE)
        self.assertIn('rule = "owner: UI work only"', T3CODE)
        self.assertIn("picker continues to enforce that this route is for UI work only", T3CODE)
        self.assertIn('rule = "owner-approved default paid worker route"', T3CODE)
        self.assertEqual(T3CODE.count('model = "claude-fable-5"'), 3)
        self.assertEqual(T3CODE.count('model = "claude-fable-5-1"'), 3)
        self.assertEqual(T3CODE.count('provider = "claudeAgent"'), 7)
        self.assertIn('authorizations = [ ];', T3CODE)
        self.assertNotIn('model = "gpt-6.1-sol"', T3CODE)


if __name__ == "__main__":
    unittest.main()
