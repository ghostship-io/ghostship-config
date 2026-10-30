"""The approved v2 route catalog reaches the controller from its one source."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T3CODE = (ROOT / "modules/self-hosted/t3code.nix").read_text()
FLAKE = (ROOT / "flake.nix").read_text()
CHECKS = (ROOT / "checks.nix").read_text()
APPROVED_FREE = json.loads(
    (ROOT / "modules/self-hosted/ai-usage/approved-free-workers.json").read_text()
)


class T3RoutePolicyTests(unittest.TestCase):
    def test_the_container_reads_the_approved_catalog_from_the_config_path(self):
        self.assertIn('GHOSTSHIP_ROUTE_POLICY_PATH = "/etc/ghostship/route-policy.json"', T3CODE)
        self.assertIn('"/etc/ghostship/route-policy.json:/etc/ghostship/route-policy.json:ro"', T3CODE)
        # One source of truth: the pinned ghostship-agent catalog file itself,
        # rendered verbatim. This repository keeps no policy copy.
        self.assertIn('routeCatalogFile = "${routeCatalog}/config/agents/route-policy.json";', T3CODE)
        self.assertIn('environment.etc."ghostship/route-policy.json".source = routeCatalogFile', T3CODE)
        self.assertIn('ghostship-route-catalog = {', FLAKE)

    def test_no_hand_maintained_schema_is_rendered_by_this_repository(self):
        self.assertNotIn('schema = "ghostship.route-policy/v1"', T3CODE)
        self.assertNotIn('schema = "ghostship.route-policy/v2"', T3CODE)
        self.assertNotIn("authorizations = [ ];", T3CODE)
        self.assertNotIn("ownerRoutePolicy", T3CODE)

    def test_the_coordinator_reads_the_same_approved_catalog(self):
        coordinator = (ROOT / "modules/self-hosted/github-engineering.nix").read_text()
        self.assertIn('GHOSTSHIP_ROUTE_POLICY_PATH = "/etc/ghostship/route-policy.json";', coordinator)
        self.assertIn('"/etc/ghostship/route-policy.json:/etc/ghostship/route-policy.json:ro"', coordinator)

    def test_the_free_allow_list_file_stays_installed_for_the_collector(self):
        self.assertIn('approvedFreeWorkers = ./ai-usage/approved-free-workers.json', T3CODE)
        self.assertIn('environment.etc."ghostship/approved-free-workers.json".source = approvedFreeWorkers', T3CODE)
        self.assertGreater(len(APPROVED_FREE["entries"]), 0)

    def test_host_evaluation_pins_the_reconciled_approval_set(self):
        # The exact owner-reconciled approvals of 2026-10-30; anything wider
        # fails host evaluation rather than shipping unapproved routes.
        for route in (
            "opencode/ollama-cloud/deepseek-v4.1-flash",
            "opencode/ollama-cloud/deepseek-v4.1-flash:1017",
            "opencode/opencode-go/deepseek-v4.1-flash",
            "opencode/command-code/deepseek/deepseek-v4.1-flash",
            "opencode/literouter/deepseek-v4.1-flash-1017:full-context",
            "antigravity/gemini-3.8-flash",
            "claudeAgent/claude-sonnet-5-5",
            "codex/gpt-6.1-terra",
        ):
            self.assertIn(f'"{route}"', CHECKS)
        self.assertIn('actualApprovedRoutes', CHECKS)
        self.assertIn('routePolicy.schema == "ghostship.route-policy/v2"', CHECKS)
        # The denied V4 Pro route stays recorded, never admitted.
        self.assertIn('r.model == "ollama-cloud/deepseek-v4-pro"', CHECKS)


if __name__ == "__main__":
    unittest.main()
