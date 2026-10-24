"""The limit probe of the T3 source, per provider instance.

The t3 source publishes the subscription windows T3 Code knows about. A
provider instance that has no usage limits to report, or whose own limits
probe failed, is a fact about that provider's probe, not a gap in the
source: the source read the provider's status, and the per-provider metric
says what the probe said. These tests pin that reading.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "modules" / "self-hosted" / "ai-usage" / "collector"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import codes  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, COLLECTOR / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


t3source = load("ai_usage_t3_limit_probe", "t3source.py")


class Client:
    """A T3 Code client that reports the given provider instances."""

    def __init__(self, providers):
        self.providers = providers

    def call(self, method, args):
        if method == "server.refreshProviders":
            return {"providers": self.providers}
        raise AssertionError(method)


def provider(instance, limits=None, models=(), status="ready"):
    entry = {
        "instanceId": instance,
        "enabled": True,
        "status": status,
        "models": list(models),
    }
    if limits is not None:
        entry["usageLimits"] = limits
    return entry


def limits(windows=(), unavailable=None):
    entry = {"checkedAt": "2026-10-24T20:30:00Z", "windows": list(windows)}
    if unavailable is not None:
        entry["unavailable"] = {"reason": unavailable}
    return entry


class LimitProbeTests(unittest.TestCase):
    def read(self, providers):
        return t3source._collect_limits(Client(providers), {})

    def probes(self, result):
        return {
            (labels["provider"], labels["state"])
            for name, labels, _value in result.metrics
            if name == "ghostship_ai_limit_probe"
        }

    def test_an_instance_with_no_limits_does_not_make_the_source_partial(self):
        result = self.read(
            [
                provider("opencode-free", limits(unavailable="unsupported")),
                provider(
                    "opencode",
                    limits(
                        windows=[
                            {
                                "id": "go_monthly",
                                "kind": "monthly",
                                "usedPercent": 100,
                                "resetsAt": "2026-10-30T22:34:27.000Z",
                            }
                        ]
                    ),
                ),
            ]
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.reason, codes.OK)
        self.assertIn(("opencode-free", "unsupported"), self.probes(result))
        self.assertIn(("opencode-go", "reported"), self.probes(result))

    def test_a_failed_probe_is_published_and_does_not_make_the_source_partial(self):
        # The source read the provider's status; the probe that the provider
        # runs for itself failed, and the per-provider metric says so. The
        # snapshot is not partial for a fact one provider states about itself.
        result = self.read(
            [provider("claudeAgent", limits(unavailable="probeFailed"))]
        )
        self.assertEqual(result.status, "ok")
        self.assertIn(("claude", "failed"), self.probes(result))

    def test_an_unsupported_instance_never_masks_a_failed_probe(self):
        result = self.read(
            [
                provider("claudeAgent", limits(unavailable="probeFailed")),
                provider("opencode-free", limits(unavailable="unsupported")),
            ]
        )
        self.assertEqual(
            self.probes(result),
            {("claude", "failed"), ("opencode-free", "unsupported")},
        )

    def test_a_ready_instance_without_a_limits_reading_is_not_a_gap(self):
        result = self.read([provider("muse")])
        self.assertEqual(result.status, "ok")
        self.assertNotIn(("muse", "failed"), self.probes(result))


if __name__ == "__main__":
    unittest.main()
