"""The capacity that the failures of a route imply.

The providers that report no usage, and every free route, showed "Limits
unknown" on the Providers page. The owner rule reads their capacity from the
limit failures instead: a route that runs until it is refused shows its
window, its budget, its scope and its remaining share in those refusals.

These tests pin every worked value of the rule. They use inline events only:
no file, no database and no network is read.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inference = load("ai_usage_inference_module", "inference.py")

# Monday 2026-01-05 00:00 UTC. Every case of a day uses this clock.
DAY0 = 1767571200.0
HOUR = 3600.0
MINUTE = 60.0


def at(day=0, hour=0, minute=0):
    """An instant on the day clock of the cases."""
    return DAY0 + day * 86400.0 + hour * HOUR + minute * MINUTE


def event(provider, model, when, outcome="success", usage=None, window_hint=None):
    """One recorded use of a route."""
    return {
        "provider": provider,
        "model": model,
        "at": when,
        "outcome": outcome,
        "usage": usage,
        "window_hint": window_hint,
    }


def route(events, now, provider="acme", model="sonnet"):
    """The capacity of one route of a record."""
    results = inference.infer_capacity(events, now)
    return results[(provider, model)]


class PolicyExampleA(unittest.TestCase):
    """Case 1: the worked example of the owner rule."""

    def setUp(self):
        self.events = [
            event("acme", "sonnet", at(0, 8), usage=200000.0),
            event("acme", "sonnet", at(0, 9), usage=400000.0),
            event("acme", "sonnet", at(0, 10, 30), outcome="limit"),
            event("acme", "sonnet", at(0, 13, 2), usage=0.0),
            event("acme", "sonnet", at(0, 13, 5), usage=150000.0),
        ]
        self.now = at(0, 14, 20)

    def test_window_budget_and_share(self):
        result = route(self.events, self.now)
        self.assertEqual(result.basis, "inferred")
        self.assertEqual(result.state, "in_window")
        self.assertEqual(result.window, "5h")
        self.assertEqual(result.window_seconds, 18000)
        self.assertEqual(result.budget, 600000.0)
        self.assertEqual(result.unit, "tokens")
        self.assertEqual(result.episodes, 1)
        self.assertAlmostEqual(result.left, 0.75)
        self.assertAlmostEqual(result.expected_left, 0.75)
        self.assertAlmostEqual(result.paced_availability, 0.0)
        self.assertAlmostEqual(result.start_at, at(0, 13, 5))
        self.assertAlmostEqual(result.reset_at, at(0, 18, 5))

    def test_every_route_of_the_record_has_a_result(self):
        results = inference.infer_capacity(self.events, self.now)
        self.assertEqual(sorted(results), [("acme", "sonnet")])
        self.assertEqual(results[("acme", "sonnet")].scope, "unknown")


class PolicyExampleB(unittest.TestCase):
    """Case 2: requests instead of tokens."""

    def test_a_week_of_requests(self):
        events = [
            event("acme", "sonnet", at(0, 9) + index * 30.0) for index in range(400)
        ]
        events.append(event("acme", "sonnet", at(4, 15), outcome="limit"))
        events.append(event("acme", "sonnet", at(7, 9, 10)))
        now = at(7, 9, 10)
        result = route(events, now)
        self.assertEqual(result.window, "7d")
        self.assertEqual(result.window_seconds, 604800)
        self.assertEqual(result.budget, 400.0)
        self.assertEqual(result.unit, "requests")
        self.assertEqual(result.episodes, 1)
        self.assertEqual(result.state, "in_window")
        self.assertAlmostEqual(result.left, 1.0)
        self.assertAlmostEqual(result.expected_left, 1.0)
        self.assertAlmostEqual(result.paced_availability, 0.0)
        self.assertAlmostEqual(result.reset_at, at(14, 9, 10))


class NamedWindow(unittest.TestCase):
    """Case 3: a limit that names its window wins over the timing."""

    def test_the_hint_wins(self):
        events = [
            event("acme", "sonnet", at(0, 8), usage=200000.0),
            event("acme", "sonnet", at(0, 9), usage=400000.0),
            event("acme", "sonnet", at(0, 10, 30), outcome="limit", window_hint="1d"),
            event("acme", "sonnet", at(0, 13, 2), usage=0.0),
            event("acme", "sonnet", at(0, 13, 5), usage=150000.0),
        ]
        result = route(events, at(0, 14, 20))
        self.assertEqual(result.window, "1d")
        self.assertEqual(result.window_seconds, 86400)
        self.assertEqual(result.budget, 600000.0)
        self.assertAlmostEqual(result.left, 0.75)
        self.assertAlmostEqual(result.expected_left, 1.0 - 4500.0 / 86400.0)
        self.assertAlmostEqual(result.paced_availability, 0.75 - (1.0 - 4500.0 / 86400.0))
        self.assertAlmostEqual(result.reset_at, at(1, 13, 5))


class Snapping(unittest.TestCase):
    """Case 4: the boundary of the snapping, by ratio."""

    def test_two_hours_snaps_to_one_hour(self):
        self.assertEqual(inference.snap_window(7200.0), "1h")

    def test_two_and_a_half_hours_snaps_to_five_hours(self):
        self.assertEqual(inference.snap_window(9000.0), "5h")

    def test_thirty_hours_snaps_to_one_day(self):
        self.assertEqual(inference.snap_window(108000.0), "1d")

    def test_the_snapping_is_used_by_the_route(self):
        events = [
            event("acme", "sonnet", at(0, 8), usage=1000.0),
            event("acme", "sonnet", at(0, 9), outcome="limit"),
            event("acme", "sonnet", at(1, 14), usage=0.0),
        ]
        result = route(events, at(1, 15))
        self.assertEqual(result.window, "1d")
        self.assertEqual(result.window_seconds, 86400)


class NoFailure(unittest.TestCase):
    """Case 5: a route that was never refused."""

    def test_no_failure(self):
        events = [
            event("acme", "sonnet", at(0, 8) + index * 60.0, usage=1000.0)
            for index in range(10)
        ]
        result = route(events, at(0, 9))
        self.assertEqual(result.state, "no_failure")
        self.assertEqual(result.left, 1.0)
        self.assertIsNone(result.paced_availability)
        self.assertIsNone(result.expected_left)
        self.assertIsNone(result.window)
        self.assertIsNone(result.window_seconds)
        self.assertIsNone(result.reset_at)
        self.assertIsNone(result.budget)
        self.assertEqual(result.episodes, 0)


class ExhaustedFirstEpisode(unittest.TestCase):
    """Case 6: the first refusal, with no history behind it."""

    def test_exhausted_without_a_known_window(self):
        events = [
            event("acme", "sonnet", at(0, 8), usage=1000.0),
            event("acme", "sonnet", at(0, 9), outcome="limit"),
        ]
        result = route(events, at(0, 9, 30))
        self.assertEqual(result.state, "exhausted")
        self.assertEqual(result.left, 0.0)
        self.assertIsNone(result.reset_at)
        self.assertIsNone(result.window)
        self.assertIsNone(result.window_seconds)
        self.assertIsNone(result.expected_left)
        self.assertIsNone(result.paced_availability)
        self.assertAlmostEqual(result.start_at, at(0, 8))


class ExhaustedWithHistory(unittest.TestCase):
    """Case 7: a refusal with a completed episode behind it."""

    def setUp(self):
        self.events = [
            event("acme", "sonnet", at(0, 8), usage=200000.0),
            event("acme", "sonnet", at(0, 9), usage=400000.0),
            event("acme", "sonnet", at(0, 10, 30), outcome="limit"),
            event("acme", "sonnet", at(0, 13, 2), usage=0.0),
            event("acme", "sonnet", at(0, 13, 5), usage=150000.0),
            event("acme", "sonnet", at(0, 15), outcome="limit"),
        ]
        self.now = at(0, 15, 30)

    def test_exhausted_with_a_known_window(self):
        result = route(self.events, self.now)
        self.assertEqual(result.state, "exhausted")
        self.assertEqual(result.left, 0.0)
        self.assertAlmostEqual(result.reset_at, at(0, 18, 5))
        self.assertEqual(result.window, "5h")
        self.assertEqual(result.window_seconds, 18000)
        self.assertAlmostEqual(result.start_at, at(0, 13, 5))
        elapsed = self.now - at(0, 13, 5)
        self.assertAlmostEqual(result.expected_left, 1.0 - elapsed / 18000.0)
        self.assertAlmostEqual(
            result.paced_availability, -(1.0 - elapsed / 18000.0)
        )


class Tiling(unittest.TestCase):
    """Case 8: the window that ended while nobody used the route."""

    def setUp(self):
        self.events = [
            event("acme", "sonnet", at(0, 8), usage=200000.0),
            event("acme", "sonnet", at(0, 9), usage=400000.0),
            event("acme", "sonnet", at(0, 10, 30), outcome="limit"),
            event("acme", "sonnet", at(0, 13, 2), usage=0.0),
            event("acme", "sonnet", at(0, 13, 5), usage=150000.0),
            event("acme", "sonnet", at(0, 18, 30), usage=60000.0),
        ]
        self.now = at(0, 19)

    def test_the_start_moves_to_the_next_use(self):
        result = route(self.events, self.now)
        self.assertAlmostEqual(result.start_at, at(0, 18, 30))
        self.assertAlmostEqual(result.expected_left, 0.9)
        self.assertAlmostEqual(result.left, 0.9)
        self.assertAlmostEqual(result.paced_availability, 0.0)
        self.assertAlmostEqual(result.reset_at, at(0, 23, 30))
        self.assertEqual(result.state, "in_window")

class ScopeModel(unittest.TestCase):
    """Case 9: another model of the same provider succeeded in the span."""

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 8), usage=1000.0),
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 11), usage=500.0),
            event("acme", "alpha", at(0, 13), usage=0.0),
        ]
        self.now = at(0, 14)

    def test_the_scope_is_the_model(self):
        result = route(self.events, self.now, model="alpha")
        self.assertEqual(result.scope, "model")
        self.assertEqual(result.window, "5h")
        self.assertEqual(result.budget, 1000.0)

    def test_the_other_route_is_unknown(self):
        result = route(self.events, self.now, model="beta")
        self.assertEqual(result.scope, "unknown")
        self.assertIsNone(result.share)


class ScopeAccount(unittest.TestCase):
    """Case 10: only failures of the other models inside the span."""

    def test_the_scope_is_the_account(self):
        events = [
            event("acme", "alpha", at(0, 8), usage=1000.0),
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 11), outcome="limit"),
            event("acme", "alpha", at(0, 13), usage=0.0),
        ]
        result = route(events, at(0, 14), model="alpha")
        self.assertEqual(result.scope, "account")
        self.assertEqual(result.window, "5h")
        self.assertEqual(result.budget, 1000.0)

    def test_no_other_model_in_the_span_is_unknown(self):
        events = [
            event("acme", "alpha", at(0, 8), usage=1000.0),
            event("acme", "beta", at(0, 9), usage=500.0),
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "alpha", at(0, 13), usage=0.0),
        ]
        result = route(events, at(0, 14), model="alpha")
        self.assertEqual(result.scope, "unknown")


if __name__ == "__main__":
    unittest.main()
