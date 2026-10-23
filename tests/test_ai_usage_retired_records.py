"""Retirements the OpenCode request record shows.

Some retirements reach the collector only through OpenCode's request
records, never through T3 Code's run history: a delegated worker's request
fails with "Model … has been deprecated" and nothing else records it. The
reader flags such a request, the wiring turns the latest flagged request of
a route into a retirement, and the collector keeps the route out of every
tier until the record shows a later success.

Every test is synthetic. Error texts use a placeholder, and nothing reads a
live database.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
TESTS = Path(__file__).resolve().parent
for path in (ROOT, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import main  # noqa: E402
import opencode_reader  # noqa: E402
import usage_inference  # noqa: E402
from test_ai_usage_retired_routes import HOUR, NOW, Harness, sample_of  # noqa: E402

DEPRECATED = "Model minimax-m3.1-flash-free has been deprecated."
FREE_PERIOD_ENDED = (
    "The free launch period for MiniMax M3.1 Flash ended on Oct 22, 2026. "
    "The `:free` variant has been retired; use the paid model instead."
)


def failed(message: str) -> dict:
    return {"error": {"type": "provider.error", "data": {"message": message}}}


def event(provider, model, at, outcome, retired=False):
    return {
        "provider": provider,
        "model": model,
        "at": at,
        "outcome": outcome,
        "usage": 0,
        "window_hint": None,
        "retired": retired,
    }


class RetirementFlagTests(unittest.TestCase):
    """The reader flags a request that says the model was retired."""

    def test_a_deprecated_model_is_flagged(self):
        self.assertTrue(opencode_reader.is_retirement(failed(DEPRECATED)))

    def test_an_ended_free_period_is_flagged(self):
        self.assertTrue(opencode_reader.is_retirement(failed(FREE_PERIOD_ENDED)))

    def test_an_end_of_life_is_flagged(self):
        self.assertTrue(
            opencode_reader.is_retirement(failed("The model x reached its end of life."))
        )

    def test_an_unavailable_endpoint_is_not_flagged(self):
        self.assertFalse(
            opencode_reader.is_retirement(
                failed("Upstream request failed: Endpoint is unavailable.")
            )
        )

    def test_a_usage_limit_is_not_flagged(self):
        self.assertFalse(opencode_reader.is_retirement(failed("Go usage limit exceeded")))

    def test_a_success_is_not_flagged(self):
        self.assertFalse(opencode_reader.is_retirement({"finish": "stop"}))

    def test_a_retirement_stays_other_for_the_inference(self):
        outcome, window = opencode_reader.classify(failed(DEPRECATED))
        self.assertEqual((outcome, window), ("other", None))


class RetirementsFromEventsTests(unittest.TestCase):
    """The latest flagged request of a route, with no success after it."""

    def test_the_latest_flagged_request_retires_the_route(self):
        retired, _ = usage_inference.retirements_from_events(
            [
                event("opencode-go", "minimax-m3.1-flash-free", 100.0, "success"),
                event("opencode-go", "minimax-m3.1-flash-free", 200.0, "other", True),
                event("opencode-go", "minimax-m3.1-flash-free", 300.0, "other", True),
            ]
        )
        record = retired["opencode-go/minimax-m3.1-flash-free"]
        self.assertEqual(record["reason"], "model_retired")
        self.assertEqual(record["first_seen"], 200.0)

    def test_a_success_after_the_flag_clears_it(self):
        retired, last = usage_inference.retirements_from_events(
            [
                event("openrouter", "m:free", 200.0, "other", True),
                event("openrouter", "m:free", 300.0, "success"),
            ]
        )
        self.assertEqual(retired, {})
        self.assertEqual(last["openrouter/m:free"], 300.0)

    def test_the_other_models_of_the_provider_are_untouched(self):
        retired, _ = usage_inference.retirements_from_events(
            [
                event("opencode-go", "minimax-m3.1-flash-free", 200.0, "other", True),
                event("opencode-go", "glm-5.3", 250.0, "success"),
            ]
        )
        self.assertEqual(list(retired), ["opencode-go/minimax-m3.1-flash-free"])

    def test_an_unflagged_failure_retires_nothing(self):
        retired, _ = usage_inference.retirements_from_events(
            [event("opencode-go", "glm-5.3", 200.0, "other", False)]
        )
        self.assertEqual(retired, {})


class MergeTests(unittest.TestCase):
    """The record's retirements join the collector's retirement record."""

    def test_a_record_retirement_is_added(self):
        merged = main.merge_record_retirements(
            {},
            {"p/m": {"provider": "p", "model": "m", "first_seen": 200.0}},
            {},
        )
        self.assertIn("p/m", merged)

    def test_the_earliest_first_seen_is_kept(self):
        merged = main.merge_record_retirements(
            {"p/m": {"provider": "p", "model": "m", "first_seen": 100.0}},
            {"p/m": {"provider": "p", "model": "m", "first_seen": 200.0}},
            {},
        )
        self.assertEqual(merged["p/m"]["first_seen"], 100.0)

    def test_a_later_success_in_the_record_clears_a_persisted_retirement(self):
        merged = main.merge_record_retirements(
            {"p/m": {"provider": "p", "model": "m", "first_seen": 100.0}},
            {},
            {"p/m": 150.0},
        )
        self.assertEqual(merged, {})


class CollectorTests(unittest.TestCase):
    """A route the request record shows retired holds no tier."""

    def _collect(self, harness, retirements, last_success=None):
        real = usage_inference.read_and_infer

        def fake(*args, **kwargs):
            reading = usage_inference.Inference()
            reading.retirements = dict(retirements)
            reading.last_success = dict(last_success or {})
            return reading

        with mock.patch.object(usage_inference, "read_and_infer", fake):
            result = harness.collect()
        self.assertIs(usage_inference.read_and_infer, real)
        return result

    def _retired(self, at):
        return {
            "opencode-go/minimax-m3.1-flash-free": {
                "provider": "opencode-go",
                "model": "minimax-m3.1-flash-free",
                "route": "opencode-go/minimax-m3.1-flash-free",
                "first_seen": at,
                "reason": "model_retired",
                "source": "opencode_events",
            }
        }

    def test_the_route_is_unavailable_and_holds_no_tier(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state()
            samples, snapshot = self._collect(harness, self._retired(NOW - HOUR))
            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                ),
                0.0,
            )
            for winners in (snapshot.get("tier_winners") or {}).values():
                self.assertNotIn(
                    ("opencode-go", "minimax-m3.1-flash-free"),
                    [(w.get("provider"), w.get("model")) for w in winners],
                )
            self.assertNotEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="glm-5.3",
                    reason="model_retired",
                ),
                0.0,
            )

    def test_the_retirement_is_remembered(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state()
            self._collect(harness, self._retired(NOW - HOUR))
            # The next run sees no retirement in the record, and the state
            # file still holds it.
            samples, _ = self._collect(harness, {})
            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                ),
                0.0,
            )

    def test_a_later_success_in_the_record_makes_it_available(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state()
            self._collect(harness, self._retired(NOW - HOUR))
            samples, _ = self._collect(
                harness, {}, {"opencode-go/minimax-m3.1-flash-free": NOW - 60.0}
            )
            self.assertIsNone(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                )
            )


if __name__ == "__main__":
    unittest.main()
