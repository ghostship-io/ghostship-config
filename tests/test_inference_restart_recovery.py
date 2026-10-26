"""The free-inference chain must recover from a switch restart.

Issue #611: a broker start burst during a T3 or worker restart hit
start-limit-hit, and Requires= propagation left auth, the scheduler and the
MCP runtime inactive. These static guards keep the unit data that prevents a
permanent stop, so a later edit cannot quietly reintroduce it without a Nix
evaluator (the host-evaluation check asserts the same values).
"""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_MODULE = (ROOT / "modules/self-hosted/inference-bridge.nix").read_text()
FREE_WORKER_MODULE = (ROOT / "modules/self-hosted/free-worker.nix").read_text()


def block(source, marker):
    """Return the brace-balanced body of the assignment named by marker."""
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
    raise AssertionError(f"unbalanced block after {marker}")


def setting(body, name):
    match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(.+?);\s*$", body, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{name} is not set")
    return match.group(1)


def optional_setting(body, name):
    try:
        return setting(body, name)
    except AssertionError:
        return ""


class InferenceRestartRecoveryTests(unittest.TestCase):
    def test_broker_retries_forever_instead_of_hitting_the_start_limit(self):
        bridge = block(BRIDGE_MODULE, "systemd.services.ghostship-inference-bridge =")
        self.assertEqual(setting(bridge, "Restart"), '"always"')
        self.assertEqual(setting(bridge, "StartLimitIntervalSec"), "0")
        self.assertEqual(setting(bridge, "StartLimitBurst"), "0")

    def test_broker_waits_for_the_worker_instead_of_requiring_its_stop(self):
        bridge = block(BRIDGE_MODULE, "systemd.services.ghostship-inference-bridge =")
        self.assertIn('"podman-ghostship-worker.service"', setting(bridge, "wants"))
        self.assertIn('"podman-ghostship-worker.service"', setting(bridge, "after"))
        self.assertNotIn('"podman-ghostship-worker.service"', optional_setting(bridge, "requires"))
        self.assertIn("podman exec --user 0:0 ghostship-worker /bin/true", BRIDGE_MODULE)

    def test_restarting_the_broker_or_auth_does_not_stop_dependents(self):
        auth = block(FREE_WORKER_MODULE, "systemd.services.ghostship-free-worker-auth =")
        scheduler = block(BRIDGE_MODULE, "systemd.services.ghostship-inference-scheduler =")
        proxy = block(BRIDGE_MODULE, "systemd.services.ghostship-inference-proxy =")
        mcp = block(BRIDGE_MODULE, "systemd.services.podman-ghostship-private-integrations =")
        self.assertIn('"ghostship-inference-bridge.service"', setting(auth, "wants"))
        self.assertNotIn('"ghostship-inference-bridge.service"', optional_setting(auth, "requires"))
        self.assertEqual(setting(scheduler, "Restart"), '"always"')
        self.assertNotIn('"ghostship-inference-bridge.service"', optional_setting(scheduler, "requires"))
        self.assertNotIn('"ghostship-free-worker-auth.service"', optional_setting(scheduler, "requires"))
        self.assertIn('"ghostship-inference-bridge.service"', setting(proxy, "wants"))
        self.assertNotIn('"ghostship-inference-bridge.service"', optional_setting(proxy, "requires"))
        self.assertIn('"ghostship-free-worker-auth.service"', setting(mcp, "wants"))
        self.assertNotIn('"ghostship-free-worker-auth.service"', optional_setting(mcp, "requires"))

    def test_socket_activation_never_reaches_a_permanent_trigger_limit(self):
        socket = block(BRIDGE_MODULE, "systemd.sockets.ghostship-inference-proxy =")
        self.assertEqual(setting(socket, "TriggerLimitIntervalSec"), "0")
        self.assertEqual(setting(socket, "TriggerLimitBurst"), "0")

    def test_stopping_each_inference_unit_signals_only_its_container_process(self):
        # Issue #639: signalling the host Podman attachment reports exit 1 for
        # an orderly stop. The stop helper signals the container process and
        # waits for both, so the real exit status (crash included) survives.
        bridge = block(BRIDGE_MODULE, "systemd.services.ghostship-inference-bridge =")
        scheduler = block(BRIDGE_MODULE, "systemd.services.ghostship-inference-scheduler =")
        self.assertIn("inference-container-stop.py", BRIDGE_MODULE)
        for unit in (bridge, scheduler):
            self.assertIn(r"--main-pid=\${MAINPID}", setting(unit, "ExecStop"))
            self.assertNotIn(" $MAINPID ", setting(unit, "ExecStop"))
        self.assertIn("ghostship_inference.server", setting(bridge, "ExecStop"))
        self.assertIn("ghostship_inference.cli serve", setting(scheduler, "ExecStop"))
        self.assertNotIn("SuccessExitStatus", BRIDGE_MODULE)


if __name__ == "__main__":
    unittest.main()
