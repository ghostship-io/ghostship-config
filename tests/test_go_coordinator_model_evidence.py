"""The served Go coordinator reads current model evidence from read-only mounts."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = (ROOT / "modules/self-hosted/github-engineering.nix").read_text()
CHECKS = (ROOT / "checks.nix").read_text()
PROFILE = (
    ROOT / "modules/self-hosted/apparmor/ghostship-go-coordinator.profile"
).read_text()


class GoCoordinatorModelEvidenceTests(unittest.TestCase):
    def test_the_canonical_sources_are_mounted_read_only(self):
        self.assertIn('host = "/var/lib/ghostship-ai-usage";', COORDINATOR)
        self.assertIn(
            'host = "${t3Home}/.local/state/ghostship/model-evidence";', COORDINATOR
        )
        for name in ("modelRouting", "modelOutcomes"):
            self.assertIn(
                f'"${{{name}.host}}:${{{name}.mount}}:ro,noexec,nosuid,nodev"',
                COORDINATOR,
            )

    def test_the_service_is_told_the_file_inside_each_mount(self):
        self.assertIn('mount = "/run/ghostship-model-routing";', COORDINATOR)
        self.assertIn('file = "routing.json";', COORDINATOR)
        self.assertIn('mount = "/run/ghostship-model-evidence";', COORDINATOR)
        self.assertIn('file = "model-evidence.jsonl";', COORDINATOR)
        self.assertIn(
            'GHOSTSHIP_MODEL_RANKINGS_PATH = "${modelRouting.mount}/${modelRouting.file}"',
            COORDINATOR,
        )
        self.assertIn(
            'GHOSTSHIP_MODEL_EVIDENCE_PATH = "${modelOutcomes.mount}/${modelOutcomes.file}"',
            COORDINATOR,
        )

    def test_the_flake_check_pins_the_live_paths_and_the_directory_acl(self):
        self.assertIn('modelRoutingHost = "/var/lib/ghostship-ai-usage";', CHECKS)
        self.assertIn(
            'modelOutcomesHost = "/srv/apps/t3code/home/.local/state/ghostship/model-evidence";',
            CHECKS,
        )
        self.assertIn(
            "goCoordinator.environment.GHOSTSHIP_MODEL_RANKINGS_PATH", CHECKS
        )
        self.assertIn("goCoordinator.environment.GHOSTSHIP_MODEL_EVIDENCE_PATH", CHECKS)
        self.assertIn("u:62033:rx", CHECKS)

    def test_the_apparmor_allowlist_covers_both_mounts(self):
        self.assertIn("/run/ghostship-model-routing/** r,", PROFILE)
        self.assertIn("/run/ghostship-model-evidence/** r,", PROFILE)


if __name__ == "__main__":
    unittest.main()
