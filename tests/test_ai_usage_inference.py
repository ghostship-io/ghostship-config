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

    def test_the_spent_window_is_the_open_episode(self):
        # An outcome that is not a limit does not start the episode, so the
        # window that is spent is the one of the open episode.
        events = list(self.events) + [
            event("acme", "sonnet", at(0, 14), outcome="other"),
        ]
        result = route(events, self.now)
        self.assertEqual(result.state, "exhausted")
        self.assertAlmostEqual(result.start_at, at(0, 13, 5))
        self.assertAlmostEqual(result.reset_at, at(0, 18, 5))


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


class FittedWeights(unittest.TestCase):
    """Case 11: an account budget shared between two models."""

    def setUp(self):
        self.events = []
        usage = [(100.0, 0.0), (0.0, 50.0), (50.0, 25.0)]
        for day, (alpha, beta) in enumerate(usage):
            self.events.append(event("acme", "alpha", at(day, 8), usage=alpha))
            self.events.append(event("acme", "beta", at(day, 8, 30), usage=beta))
            self.events.append(event("acme", "alpha", at(day, 9), outcome="limit"))
            self.events.append(event("acme", "beta", at(day, 9, 20), outcome="limit"))
            self.events.append(event("acme", "alpha", at(day, 9, 40), outcome="limit"))
            self.events.append(event("acme", "beta", at(day, 9, 50), outcome="limit"))
            self.events.append(event("acme", "alpha", at(day, 11), usage=0.0))
            self.events.append(event("acme", "beta", at(day, 11), usage=0.0))
        self.events.append(event("acme", "alpha", at(2, 12), usage=40.0))
        self.events.append(event("acme", "beta", at(2, 12, 5), usage=10.0))
        self.now = at(2, 12, 30)

    def test_the_weights_are_fitted(self):
        results = inference.infer_capacity(self.events, self.now)
        for result in results.values():
            self.assertEqual(result.scope, "account")
            self.assertEqual(result.weights_basis, "fitted")
            self.assertAlmostEqual(result.weights["alpha"], 0.01, delta=1e-6)
            self.assertAlmostEqual(result.weights["beta"], 0.02, delta=1e-6)
            self.assertEqual(result.budget, 1.0)
            self.assertAlmostEqual(result.left, 0.4)

    def test_the_shares_of_the_models(self):
        results = inference.infer_capacity(self.events, self.now)
        self.assertAlmostEqual(results[("acme", "alpha")].share, 0.6666667, delta=1e-6)
        self.assertAlmostEqual(results[("acme", "beta")].share, 0.3333333, delta=1e-6)


class AssumedWeights(unittest.TestCase):
    """Case 12: one account episode, so the weights stay equal."""

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 8), usage=300000.0),
            event("acme", "beta", at(0, 8, 30), usage=300000.0),
            event("acme", "alpha", at(0, 9), outcome="limit"),
            event("acme", "beta", at(0, 9, 20), outcome="limit"),
            event("acme", "alpha", at(0, 9, 40), outcome="limit"),
            event("acme", "beta", at(0, 9, 50), outcome="limit"),
            event("acme", "alpha", at(0, 11), usage=0.0),
            event("acme", "beta", at(0, 11), usage=0.0),
            event("acme", "alpha", at(0, 12), usage=100000.0),
            event("acme", "beta", at(0, 12, 5), usage=50000.0),
        ]
        self.now = at(0, 12, 30)

    def test_the_weights_are_assumed(self):
        results = inference.infer_capacity(self.events, self.now)
        for result in results.values():
            self.assertEqual(result.scope, "account")
            self.assertEqual(result.weights_basis, "assumed")
            self.assertEqual(result.weights["alpha"], 1.0)
            self.assertEqual(result.weights["beta"], 1.0)
            self.assertEqual(result.budget, 600000.0)
            self.assertAlmostEqual(result.left, 0.75)


class MedianAndMode(unittest.TestCase):
    """Case 13: the most common window wins, the median sets the budget."""

    def setUp(self):
        usage = [100.0, 200.0, 999.0, 300.0, 999.0]
        hints = ["5h", "5h", "1d", "5h", "1d"]
        self.events = []
        for day, (amount, hint) in enumerate(zip(usage, hints)):
            self.events.append(event("acme", "alpha", at(day, 8), usage=amount))
            self.events.append(
                event("acme", "alpha", at(day, 10), outcome="limit", window_hint=hint)
            )
            self.events.append(event("acme", "beta", at(day, 11), usage=500.0))
            self.events.append(event("acme", "alpha", at(day, 13), usage=0.0))
        self.now = at(4, 14)

    def test_the_mode_and_the_median(self):
        result = route(self.events, self.now, model="alpha")
        self.assertEqual(result.scope, "model")
        self.assertEqual(result.window, "5h")
        self.assertEqual(result.window_seconds, 18000)
        self.assertEqual(result.budget, 200.0)
        self.assertEqual(result.episodes, 5)


class SingleModelAccount(unittest.TestCase):
    """An account that carries usage in one model is never fitted.

    The weights are fitted only when the episodes of the account involve at
    least two models with usage and there are more episodes than those models.
    An account that carries usage in a single model has nothing to share, so
    its weights stay equal and its budget is the median usage of its episodes
    in its own unit, exactly like the budget of a route that carries its own
    limit.
    """

    def setUp(self):
        self.events = []
        for day, usage in enumerate((100.0, 300.0, 200.0)):
            self.events.append(event("acme", "alpha", at(day, 8), usage=usage))
            self.events.append(event("acme", "alpha", at(day, 9), outcome="limit"))
            self.events.append(event("acme", "beta", at(day, 9, 30), outcome="limit"))
            self.events.append(event("acme", "alpha", at(day, 11), usage=0.0))
        self.events.append(event("acme", "alpha", at(2, 12), usage=50.0))
        self.now = at(2, 12, 30)

    def test_the_weights_stay_assumed(self):
        result = route(self.events, self.now, model="alpha")
        self.assertEqual(result.scope, "account")
        self.assertEqual(result.weights_basis, "assumed")
        self.assertEqual(result.weights["alpha"], 1.0)
        self.assertEqual(result.weights["beta"], 1.0)
        self.assertEqual(result.budget, 200.0)
        self.assertEqual(result.unit, "tokens")
        self.assertEqual(result.episodes, 3)
        self.assertAlmostEqual(result.left, 0.75)


class TwoModelsTwoEpisodes(unittest.TestCase):
    """Two models with usage, but no more episodes than models: assumed.

    The fit needs more episodes than the models of the mix, so two episodes
    of two models keep the equal weights, and the budget is the median of the
    summed usage of the episodes of the account.
    """

    def setUp(self):
        self.events = []
        for day, (alpha, beta) in enumerate(((100.0, 50.0), (300.0, 100.0))):
            self.events.append(event("acme", "alpha", at(day, 8), usage=alpha))
            self.events.append(event("acme", "beta", at(day, 8, 30), usage=beta))
            self.events.append(event("acme", "alpha", at(day, 9), outcome="limit"))
            self.events.append(event("acme", "beta", at(day, 9, 30), outcome="limit"))
            self.events.append(event("acme", "alpha", at(day, 11), usage=0.0))
        self.events.append(event("acme", "alpha", at(1, 12), usage=60.0))
        self.events.append(event("acme", "beta", at(1, 12, 5), usage=40.0))
        self.now = at(1, 12, 30)

    def test_the_weights_stay_assumed(self):
        result = route(self.events, self.now, model="alpha")
        self.assertEqual(result.scope, "account")
        self.assertEqual(result.weights_basis, "assumed")
        self.assertEqual(result.weights["alpha"], 1.0)
        self.assertEqual(result.weights["beta"], 1.0)
        # The median of the summed usage of the two episodes: 150 and 400.
        self.assertEqual(result.budget, 275.0)
        self.assertAlmostEqual(result.left, 1.0 - 100.0 / 275.0)


class OtherOutcomes(unittest.TestCase):
    """Case 14: an outcome that is not a limit starts and ends nothing."""

    def test_other_events_never_make_an_episode(self):
        events = [
            event("acme", "sonnet", at(0, 8), usage=1000.0),
            event("acme", "sonnet", at(0, 9), outcome="other"),
            event("acme", "sonnet", at(0, 9, 30), outcome="other"),
            event("acme", "sonnet", at(0, 10), usage=1000.0),
        ]
        result = route(events, at(0, 11))
        self.assertEqual(result.state, "no_failure")
        self.assertEqual(result.left, 1.0)
        self.assertEqual(result.episodes, 0)
        self.assertIsNone(result.paced_availability)


class Interface(unittest.TestCase):
    """The shape of the result is fixed for the readers that come later."""

    def test_the_result_carries_every_field(self):
        events = [
            event("acme", "sonnet", at(0, 8), usage=1000.0),
            event("acme", "sonnet", at(0, 9), outcome="limit"),
            event("acme", "sonnet", at(0, 10), usage=0.0),
        ]
        result = route(events, at(0, 11))
        for field in (
            "basis",
            "state",
            "left",
            "expected_left",
            "paced_availability",
            "window",
            "window_seconds",
            "start_at",
            "reset_at",
            "budget",
            "unit",
            "scope",
            "weights",
            "weights_basis",
            "episodes",
            "share",
        ):
            self.assertIn(field, result.as_dict(), field)
            self.assertEqual(result[field], result.as_dict()[field])

    def test_the_states_are_the_three_of_the_rule(self):
        events = [event("acme", "sonnet", at(0, 8), usage=1000.0)]
        self.assertEqual(route(events, at(0, 9)).state, "no_failure")
        events.append(event("acme", "sonnet", at(0, 9), outcome="limit"))
        self.assertEqual(route(events, at(0, 9, 30)).state, "exhausted")
        events.append(event("acme", "sonnet", at(0, 10), usage=0.0))
        self.assertEqual(route(events, at(0, 10, 30)).state, "in_window")

    def test_an_empty_record_has_no_route(self):
        self.assertEqual(inference.infer_capacity([], at(0, 9)), {})

    def test_events_after_now_are_not_part_of_the_record(self):
        events = [
            event("acme", "sonnet", at(0, 8), usage=1000.0),
            event("acme", "sonnet", at(0, 20), outcome="limit"),
        ]
        result = route(events, at(0, 9))
        self.assertEqual(result.state, "no_failure")


class ScopeFromTheOpenEpisode(unittest.TestCase):
    """The open episode of a route is evidence for its scope.

    A route that was refused and never recovered has an episode too. The
    use of another model of the provider after that refusal is the evidence
    that the refusal was the model's own.
    """

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 9), usage=1000.0),
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 10, 1), usage=500.0),
            event("acme", "beta", at(0, 10, 30), usage=500.0),
        ]
        self.now = at(0, 11)

    def test_the_refused_route_is_the_model(self):
        result = route(self.events, self.now, model="alpha")
        self.assertEqual(result.scope, "model")
        self.assertEqual(result.state, "exhausted")
        self.assertEqual(result.left, 0.0)
        self.assertIsNone(result.window)
        self.assertIsNone(result.window_seconds)

    def test_the_route_that_was_never_refused_stays_out_of_the_group(self):
        result = route(self.events, self.now, model="beta")
        self.assertEqual(result.state, "no_failure")
        self.assertEqual(result.left, 1.0)
        self.assertIsNone(result.window)
        self.assertIsNone(result.budget)
        self.assertEqual(result.episodes, 0)
        self.assertIsNone(result.share)
        # The weights of a route that is measured on its own are its own.
        self.assertEqual(dict(result.weights), {"beta": 1.0})


class MergedAccountEpisode(unittest.TestCase):
    """The routes of an account share one episode when they were refused.

    Two models of a provider that were refused one after the other, and that
    came back one after the other, share the episode of the account: the
    recovery of the account is the first success after the refusal, on a
    route of the account.
    """

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 9), usage=1000.0),
            event("acme", "beta", at(0, 9), usage=500.0),
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 10, 5), outcome="limit"),
            event("acme", "alpha", at(0, 15), usage=0.0),
            event("acme", "beta", at(0, 15, 2), usage=0.0),
        ]
        self.now = at(0, 16)

    def test_both_routes_are_the_account(self):
        results = inference.infer_capacity(self.events, self.now)
        for model in ("alpha", "beta"):
            result = results[("acme", model)]
            self.assertEqual(result.scope, "account", model)
            # One merged episode, and the window of six hours snaps to five.
            self.assertEqual(result.episodes, 1, model)
            self.assertEqual(result.window, "5h", model)
            self.assertEqual(result.window_seconds, 18000, model)
            self.assertEqual(result.budget, 1500.0, model)

    def test_the_recovery_of_the_account_is_the_first_success(self):
        # The recovery of the account is the success of alpha at 15:00, so
        # beta shares that episode: the success of alpha at 15:00 is inside
        # the span of the episode, which would make beta's limit its own.
        results = inference.infer_capacity(self.events, self.now)
        self.assertEqual(results[("acme", "beta")].scope, "account")


class LiveGoProvider(unittest.TestCase):
    """The paid routes of a provider, and the free route that keeps working.

    The paid models of the provider were refused and never came back, and the
    free model of the same provider kept working every few minutes. The free
    model was never refused, so it is measured on its own, and its use never
    ends the episode of the paid models: they stay the models that were
    refused, and no minute long window is read out of their failures.
    """

    def setUp(self):
        self.events = []
        for model, minute in (("go-paid-a", 0), ("go-paid-b", 1)):
            self.events.append(event("go", model, at(0, 8, minute), usage=1000.0))
            self.events.append(event("go", model, at(0, 8, 4), outcome="limit"))
            self.events.append(event("go", model, at(0, 9, 10), outcome="limit"))
        for index in range(52):
            self.events.append(
                event("go", "go-free", at(0, 8, 5 + index * 2), usage=100.0)
            )
        self.now = at(0, 10)

    def test_the_paid_routes_are_their_own_models(self):
        for model in ("go-paid-a", "go-paid-b"):
            result = route(self.events, self.now, provider="go", model=model)
            self.assertEqual(result.scope, "model", model)
            self.assertEqual(result.state, "exhausted", model)
            self.assertEqual(result.left, 0.0, model)
            self.assertIsNone(result.window, model)
            self.assertEqual(result.episodes, 0, model)

    def test_the_free_route_is_measured_on_its_own(self):
        result = route(self.events, self.now, provider="go", model="go-free")
        self.assertEqual(result.state, "no_failure")
        self.assertEqual(result.left, 1.0)
        self.assertIsNone(result.window)
        self.assertEqual(result.episodes, 0)

    def test_no_minute_long_window_is_read(self):
        results = inference.infer_capacity(self.events, self.now)
        for (provider, model), result in results.items():
            self.assertNotEqual(result.window, "1m", f"{provider}/{model}")
            self.assertIsNone(result.window, f"{provider}/{model}")


class TheRefusalThatStartsTheEpisode(unittest.TestCase):
    """Case A: a route that was refused before it ever came back.

    The record of the provider begins with the refusal of the route, and the
    route never succeeded again. The refusal itself starts the episode, so the
    route has an open episode, and that episode is evidence for its scope:
    the other model of the provider works after the refusal, so the refusal
    was the model's own. The model that was never refused is measured on its
    own, and it never joins an account.
    """

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 10, 1), usage=500.0),
            event("acme", "beta", at(0, 10, 30), usage=500.0),
        ]
        self.now = at(0, 11)

    def test_the_refusal_is_the_model_of_the_route(self):
        result = route(self.events, self.now, model="alpha")
        self.assertEqual(result.scope, "model")
        self.assertEqual(result.state, "exhausted")
        self.assertEqual(result.left, 0.0)
        self.assertIsNone(result.window)
        self.assertIsNone(result.window_seconds)
        self.assertIsNone(result.budget)
        self.assertEqual(result.episodes, 0)

    def test_the_route_that_was_never_refused_is_alone(self):
        result = route(self.events, self.now, model="beta")
        self.assertEqual(result.state, "no_failure")
        self.assertEqual(result.left, 1.0)
        self.assertIsNone(result.window)
        self.assertIsNone(result.budget)
        self.assertEqual(result.episodes, 0)
        self.assertIsNone(result.share)
        # The weights of a route that is measured on its own are its own.
        self.assertEqual(dict(result.weights), {"beta": 1.0})


class TheAccountOfTwoRefusedRoutes(unittest.TestCase):
    """Case B: two routes of a provider that were both refused.

    The routes of the account share one episode: the refusal of the account
    is the first refusal of the group, and the recovery of the account is
    the first success after it, on a route of the account. The span of that
    episode holds the refusal of the other route and no success, so the
    limit of both routes is the account's.
    """

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 9), usage=1000.0),
            event("acme", "beta", at(0, 9), usage=500.0),
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 10, 5), outcome="limit"),
            event("acme", "alpha", at(0, 15), usage=0.0),
            event("acme", "beta", at(0, 15, 2), usage=0.0),
        ]
        self.now = at(0, 16)

    def test_both_routes_are_the_account(self):
        results = inference.infer_capacity(self.events, self.now)
        for model in ("alpha", "beta"):
            result = results[("acme", model)]
            self.assertEqual(result.scope, "account", model)
            # One merged episode: the refusal of the account is the refusal
            # of alpha, and the recovery of the account is its success.
            self.assertEqual(result.episodes, 1, model)
            # The episode runs from 09:00 to 15:00: six hours, which snaps to
            # the five hour window.
            self.assertEqual(result.window, "5h", model)
            self.assertEqual(result.window_seconds, 18000, model)
            self.assertEqual(result.budget, 1500.0, model)
            self.assertEqual(result.state, "in_window", model)

    def test_the_recovery_of_the_account_is_the_first_success(self):
        # The recovery of the account is the success of alpha at 15:00, so
        # the success of beta at 15:02 is behind it and never enters the
        # span of the episode. The refusal of alpha at 10:00 is inside that
        # span, so the limit of beta is the account's and not its own.
        results = inference.infer_capacity(self.events, self.now)
        self.assertEqual(results[("acme", "beta")].scope, "account")


class ThePaidRoutesAndTheFreeRouteOfOneProvider(unittest.TestCase):
    """Case C: the live regression of the provider that mixes paid and free.

    Two paid routes of a provider were refused and never came back, and the
    free route of the same provider kept working every few minutes. The free
    route was never refused, so it is measured on its own, and its use never
    ends the episode of the paid routes. The paid routes are the models that
    were refused: the free route works after their refusal, so their limits
    were their own, and no minute long window is read out of their failures.
    """

    def setUp(self):
        self.events = [
            event("go", "go-paid-a", at(0, 8), usage=1000.0),
            event("go", "go-paid-a", at(0, 8, 4), outcome="limit"),
            event("go", "go-paid-b", at(0, 8, 1), usage=1000.0),
            event("go", "go-paid-b", at(0, 9, 10), outcome="limit"),
        ]
        for index in range(58):
            self.events.append(
                event("go", "go-free", at(0, 8, 5 + index * 2), usage=100.0)
            )
        self.now = at(0, 10)

    def test_the_paid_routes_are_their_own_models(self):
        for model in ("go-paid-a", "go-paid-b"):
            result = route(self.events, self.now, provider="go", model=model)
            self.assertEqual(result.scope, "model", model)
            self.assertEqual(result.state, "exhausted", model)
            self.assertEqual(result.left, 0.0, model)
            self.assertIsNone(result.window, model)
            self.assertEqual(result.episodes, 0, model)

    def test_the_free_route_is_measured_on_its_own(self):
        result = route(self.events, self.now, provider="go", model="go-free")
        self.assertEqual(result.state, "no_failure")
        self.assertEqual(result.left, 1.0)
        self.assertIsNone(result.window)
        self.assertIsNone(result.budget)
        self.assertEqual(result.episodes, 0)

    def test_no_minute_long_window_is_read(self):
        results = inference.infer_capacity(self.events, self.now)
        for (provider, model), result in results.items():
            self.assertNotEqual(result.window, "1m", f"{provider}/{model}")
            self.assertIsNone(result.window, f"{provider}/{model}")


class TheSpanOfAnOpenEpisode(unittest.TestCase):
    """The span of an open episode runs from after the refusal.

    The refusal itself is never evidence of the scope: the span of an open
    episode runs from after the refusal to the reading. Two routes of a
    provider that were refused at the same instant have nothing in that
    span, so the scope of each is unknown, and both are measured across the
    account.
    """

    def setUp(self):
        self.events = [
            event("acme", "alpha", at(0, 10), outcome="limit"),
            event("acme", "beta", at(0, 10), outcome="limit"),
        ]
        self.now = at(0, 11)

    def test_the_refusal_is_not_evidence_of_the_scope(self):
        for model in ("alpha", "beta"):
            result = route(self.events, self.now, model=model)
            self.assertEqual(result.scope, "unknown", model)
            self.assertEqual(result.state, "exhausted", model)
            self.assertEqual(result.left, 0.0, model)
            self.assertIsNone(result.window, model)


if __name__ == "__main__":
    unittest.main()
