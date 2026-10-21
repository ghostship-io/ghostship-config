"""SIEM pipeline watchdog (modules/self-hosted/siem/watchdog.py)."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "siem_watchdog", Path(__file__).resolve().parents[1] / "modules/self-hosted/siem/watchdog.py")
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

CONFIG = {"sources": ["logs", "metrics"], "probes": {"vmalert-logs": "x"}, "bridge_stale": 180,
          "source_stale": 300, "delivery_failures": 3, "snapshot_stale": 300}
NOW = 10_000


def bridge(poll=NOW - 30, logs=NOW - 30, metrics=NOW - 30, ntfy_fail=0, dead=0):
    return "\n".join([
        f"ghostship_siem_bridge_last_poll_timestamp_seconds {poll}",
        f'ghostship_siem_bridge_source_last_success_timestamp_seconds{{source="logs"}} {logs}',
        f'ghostship_siem_bridge_source_last_success_timestamp_seconds{{source="metrics"}} {metrics}',
        f'ghostship_siem_bridge_delivery_consecutive_failures{{channel="ntfy"}} {ntfy_fail}',
        f"ghostship_siem_bridge_dead_letters {dead}",
    ])


def found(text, mtime=NOW - 30, snap=NOW - 30, up=True):
    return wd.problems(CONFIG, NOW, text, mtime, snap, probe=lambda url: up)


class ProblemTests(unittest.TestCase):
    def test_healthy_pipeline_is_quiet(self):
        self.assertEqual(found(bridge()), {})

    def test_hung_bridge_with_fresh_file_or_stale_file(self):
        self.assertIn("bridge-stalled", found(bridge(poll=NOW - 600)))
        self.assertIn("bridge-stalled", found(bridge(), mtime=NOW - 600))
        self.assertIn("bridge-stalled", found(None))

    def test_unavailable_vmalert_and_store(self):
        self.assertIn("source-logs", found(bridge(logs=NOW - 900)))
        self.assertIn("probe-vmalert-logs", found(bridge(), up=False))

    def test_delivery_failures_dead_letters_and_snapshot(self):
        result = found(bridge(ntfy_fail=3, dead=1), snap=None)
        self.assertEqual({"delivery-ntfy", "dead-letters", "snapshot-stale"}, set(result))


class EpisodeTests(unittest.TestCase):
    def test_one_incident_per_episode_retry_until_delivered_then_resolve_once(self):
        sent, state = [], {}
        ntfy_up = [False]

        def send(state_name, key, message, incident):
            sent.append((state_name, key, incident))
            return ntfy_up[0]

        wd.step(state, {"bridge-stalled": "m"}, 1, send)   # ntfy down: incident queued
        wd.step(state, {"bridge-stalled": "m"}, 2, send)   # retry, no second incident
        ntfy_up[0] = True
        wd.step(state, {"bridge-stalled": "m"}, 3, send)   # delivered
        wd.step(state, {"bridge-stalled": "m"}, 4, send)   # quiet while it persists
        wd.step(state, {}, 5, send)                         # resolved once
        wd.step(state, {}, 6, send)
        self.assertEqual(sent, [("firing", "bridge-stalled", True), ("firing", "bridge-stalled", False),
                                ("firing", "bridge-stalled", False), ("resolved", "bridge-stalled", False)])
        self.assertEqual(state["episodes"], {})


if __name__ == "__main__":
    unittest.main()
