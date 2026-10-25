"""A changed host-pinned agent release refreshes without a bridge restart."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "managed_agent_release_refresh",
    ROOT / "modules/self-hosted/managed-agent-release-refresh.py",
)
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


class ManagedAgentReleaseRefreshTests(unittest.TestCase):
    def test_generation_activation_refreshes_only_when_its_release_differs(self):
        module = (ROOT / "modules/self-hosted/inference-bridge.nix").read_text()
        refresh_service = module.split(
            "systemd.services.ghostship-managed-agent-release-refresh = {", 1
        )[1].split("systemd.services.ghostship-inference-bridge = {", 1)[0]
        self.assertIn("wantedBy = [ \"multi-user.target\" ]", refresh_service)
        self.assertIn('after = [ "podman-t3code.service" ]', refresh_service)
        self.assertIn('requires = [ "podman-t3code.service" ]', refresh_service)
        self.assertIn("restartTriggers = [ inputs.ghostship-private-agent ]", refresh_service)
        self.assertIn("RemainAfterExit = true", refresh_service)
        self.assertIn("ExecStartPre = managedAgentReleasePublish", refresh_service)
        self.assertIn("ExecStart = managedAgentReleaseRefresh", refresh_service)
        self.assertIn("managed-agent-release-refresh.py", module)
        self.assertIn('"--refresh" "--managed-only"', module)

        with tempfile.TemporaryDirectory() as temporary:
            installed_path = Path(temporary) / "release.json"
            deployed_path = Path(temporary) / "host-release.json"
            installed = {
                "version": "0.47.131", "source": "/fixture/old-source",
                "revision": "a" * 40, "package": "/nix/store/old-agent",
            }
            deployed = {
                "version": "0.47.131", "source": "/fixture/old-source",
                "revision": "a" * 40, "package": "/nix/store/old-agent",
            }
            installed_path.write_text(json.dumps(installed))
            deployed_path.write_text(json.dumps(deployed))
            with patch.object(refresh.subprocess, "run") as run:
                self.assertFalse(refresh.refresh_if_needed(installed_path, deployed_path, ["podman", "exec"]))
                run.assert_not_called()

                deployed["version"] = "0.47.132"
                deployed["package"] = "/nix/store/new-agent"
                deployed_path.write_text(json.dumps(deployed))
                self.assertTrue(refresh.refresh_if_needed(installed_path, deployed_path, ["podman", "exec"]))
                run.assert_called_once_with(["podman", "exec"], check=True)

    def test_missing_installed_record_requests_a_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "release.json"
            deployed = Path(temporary) / "host-release.json"
            deployed.write_text(json.dumps({
                "version": "0.47.132", "source": "/fixture/source",
                "revision": "b" * 40, "package": "/nix/store/agent",
            }))
            with patch.object(refresh.subprocess, "run") as run:
                self.assertTrue(refresh.refresh_if_needed(installed, deployed, ["podman", "exec"]))
                run.assert_called_once_with(["podman", "exec"], check=True)


if __name__ == "__main__":
    unittest.main()
