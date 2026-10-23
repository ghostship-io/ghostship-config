"""The display quality score of a model: one number, every page.

The owner asked for one quality score per model, shown for every model on
every page - orchestrators, workers, 3D and free - so all panes read the same
comparable number. The tier order is unchanged; this is the display score.

The score is the outcome quality the ranking is valued by, as an integer:

    p0 = 0.5 + 0.4 * (I - I_min_all) / (I_max_all - I_min_all)
    score = round(100 * (k * p0 + s) / (k + n)), k = 10

The range of the prior is every ranked candidate, across every tier, and the
counts are every task type of the model identity. The score therefore does
not change between tiers, and it does not order one.
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


value_policy = load("quality_score_value_policy", "value_policy.py")
snapshot = load("quality_score_snapshot", "snapshot.py")
main = load("quality_score_main", "main.py")

FIELDS = ("quality_score", "quality_p0", "quality_n", "quality_s", "quality_basis")


def row(provider, model, strength, tiers=("bulk",)):
    """A candidate row that holds every tier it names, with a measured I."""
    return {
        "provider": provider,
        "model": model,
        "tiers": list(tiers),
        "availability": {"state": "available"},
        "admission": {"state": "settled"},
        "aa": {
            "state": "measured",
            "reference": {"id": model},
            "selectable": True,
        },
        "selection": {"excluded": False, "frontier_workhorse": True},
        "eligibility": {
            "frontier_prime": {"allowed": True},
            "delegate": {"allowed": True},
        },
        "reserve": {"3d": False, "withheld": False},
        "value": {
            "strength": strength,
            "components": {"cost_per_task": {"value": 0.5}},
        },
        "value_3d": {"value": 0.5},
        "access": {"billing": "paid"},
        "capacity": {"pace_delta": 0.0},
        "quota_state": "available",
    }


def round_(model, task_type, verdict, cause=None, index=0):
    """One ledger round, in the shape the outcomes are read in."""
    return {
        "round_id": f"r-{index}",
        "model": model,
        "task_type": task_type,
        "verdict": verdict,
        "verdict_source": "manual",
        "cause": cause,
        "fabrication": 0,
        "started_at": f"2026-10-22T{index:02d}:00:00Z",
    }


def trust_of(rounds):
    """The trust and the outcomes of the rounds, read once."""
    return snapshot._Trust(
        {"identities": {}, "policy": {}, "rounds": rounds, "backfill": []}
    )


def scored(candidates, rounds=()):
    """Fill the trust and the display score of the candidates, as a run does."""
    snapshot._fill_trust(candidates, trust_of(list(rounds)))
    return candidates


class QualityScoreMathsTests(unittest.TestCase):
    """The maths of the score: the prior, the counts and the rounding."""

    def test_the_top_of_the_range_with_no_rounds_is_90(self):
        # I = 45.1 at the top of 24.7..45.1: p0 is the ceiling, and 10 prior
        # outcomes with none observed leave it there.
        self.assertAlmostEqual(
            value_policy.outcome_prior(45.1, 24.7, 45.1), 0.900, places=4
        )
        self.assertEqual(value_policy.quality_score(0.900, 0, 0), 90)

    def test_23_of_28_accepted_is_83(self):
        # I = 42.7 in the range: p0 = 0.8529, and (10 * 0.8529 + 23) / 38
        # is 0.8297, so the display score is 83.
        self.assertAlmostEqual(
            value_policy.outcome_prior(42.7, 24.7, 45.1), 0.8529, places=4
        )
        self.assertEqual(value_policy.quality_score(0.85294, 28, 23), 83)

    def test_the_neutral_prior_with_no_evidence_is_50(self):
        self.assertEqual(value_policy.quality_score(0.5, 0, 0), 50)

    def test_the_score_is_an_integer_in_the_display_range(self):
        for p0, n, s in ((0.5, 0, 0), (0.9, 0, 0), (0.8529, 28, 23), (0.5, 1, 1)):
            with self.subTest(p0=p0, n=n, s=s):
                score = value_policy.quality_score(p0, n, s)
                self.assertIsInstance(score, int)
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)

    def test_an_impossible_count_is_rejected(self):
        with self.assertRaises(ValueError):
            value_policy.quality_score(0.5, 2, 3)


class QualityScoreRowTests(unittest.TestCase):
    """Every candidate row and every winner carries the five fields."""

    def test_the_top_of_the_global_range_is_90_aa_only(self):
        rows = scored(
            [
                row("a", "low", 24.7),
                row("b", "top", 45.1),
            ]
        )
        top = {entry["model"]: entry for entry in rows}["top"]
        self.assertEqual(top["quality_score"], 90)
        self.assertAlmostEqual(top["quality_p0"], 0.900, places=4)
        self.assertEqual(top["quality_n"], 0)
        self.assertEqual(top["quality_s"], 0)
        self.assertEqual(top["quality_basis"], "AA only")

    def test_23_of_28_accepted_publishes_83_aa_and_outcomes(self):
        # The implementation task type alone is 12 rounds of 10 accepted;
        # the 3D task type is 16 of 13. The display score reads all 28.
        rounds = (
            [round_("m", "implementation", "accepted", index=i) for i in range(10)]
            + [round_("m", "implementation", "reworked", index=10 + i) for i in range(2)]
            + [round_("m", "cad-execution", "accepted", index=20 + i) for i in range(13)]
            + [round_("m", "cad-execution", "reworked", index=33 + i) for i in range(3)]
        )
        rows = scored(
            [
                row("a", "low", 24.7),
                row("b", "m", 42.7),
                row("c", "top", 45.1),
            ],
            rounds,
        )
        scored_row = {entry["model"]: entry for entry in rows}["m"]
        self.assertAlmostEqual(scored_row["quality_p0"], 0.8529, places=4)
        self.assertEqual(scored_row["quality_n"], 28)
        self.assertEqual(scored_row["quality_s"], 23)
        self.assertEqual(scored_row["quality_score"], 83)
        self.assertEqual(scored_row["quality_basis"], "AA + outcomes")
        # The per-tier outcome keeps the rounds of its own task type: the
        # display score is the global one, not the tier's.
        self.assertEqual(scored_row["outcome"]["bulk"]["n"], 12)

    def test_no_aa_and_no_rounds_is_50_default_prior(self):
        rows = scored([row("a", "unknown", None)])
        entry = rows[0]
        self.assertIsNone(entry["value"]["strength"])
        self.assertEqual(entry["quality_score"], 50)
        self.assertAlmostEqual(entry["quality_p0"], 0.5, places=4)
        self.assertEqual(entry["quality_n"], 0)
        self.assertEqual(entry["quality_basis"], "default prior")

    def test_a_brief_caused_rework_is_not_in_the_global_counts(self):
        rounds = (
            [round_("m", "implementation", "accepted", index=i) for i in range(3)]
            + [round_("m", "implementation", "reworked", cause="brief", index=9)]
        )
        rows = scored([row("a", "m", 45.1)], rounds)
        entry = rows[0]
        self.assertEqual(entry["quality_n"], 3)
        self.assertEqual(entry["quality_s"], 3)
        self.assertEqual(entry["quality_basis"], "AA + outcomes")

    def test_every_candidate_row_and_winner_carries_the_fields(self):
        rows = scored([row("a", "m", 45.1)], [round_("m", "implementation", "accepted")])
        for field in FIELDS:
            self.assertIn(field, rows[0])
        winners, _coverage = snapshot._winners(
            rows, {"bulk": [snapshot._key("a", "m")]}, aa_cache={"status": "ok"}
        )
        winner = winners["bulk"][0]
        for field in FIELDS:
            self.assertIn(field, winner)
        for field in ("quality_score", "quality_p0", "quality_n", "quality_s"):
            self.assertEqual(winner[field], rows[0][field])
        self.assertEqual(winner["quality_basis"], rows[0]["quality_basis"])


class QualityScoreTierInvarianceTests(unittest.TestCase):
    """One number per model: the tier it holds never changes the score."""

    def test_the_score_of_one_model_is_the_same_in_every_tier(self):
        # The same row holds the bulk and the 3D tier. Its per-tier outcome
        # reads the implementation rounds in the bulk tier and the
        # cad-execution rounds in the 3D tier, but the display score reads
        # both task types: it is one number, and the winners agree.
        rounds = (
            [round_("m", "implementation", "accepted", index=i) for i in range(2)]
            + [round_("m", "cad-execution", "rejected", index=5 + i) for i in range(2)]
        )
        rows = scored([row("a", "m", 45.1, tiers=("bulk", "3d"))], rounds)
        entry = rows[0]
        self.assertEqual(entry["quality_n"], 4)
        self.assertEqual(entry["quality_s"], 2)
        winners, _coverage = snapshot._winners(
            rows,
            {"bulk": [snapshot._key("a", "m")], "3d": [snapshot._key("a", "m")]},
            aa_cache={"status": "ok"},
        )
        bulk = winners["bulk"][0]
        threed = winners["3d"][0]
        self.assertEqual(bulk["quality_score"], entry["quality_score"])
        self.assertEqual(threed["quality_score"], entry["quality_score"])
        self.assertNotEqual(
            bulk["outcome"]["p"],
            threed["outcome"]["p"],
            "the per-tier outcome differs, so an equality of the scores is real",
        )

    def test_the_tier_order_does_not_read_the_display_score(self):
        rows = scored(
            [
                row("a", "low", 24.7),
                row("a", "high", 45.1),
                row("b", "other", 30.0),
            ],
            [round_("high", "implementation", "accepted")],
        )
        before = {
            entry["model"]: snapshot._winner_key(entry, "bulk") for entry in rows
        }
        # The score is beside the key, not inside it: removing the display
        # fields leaves every tier key exactly as it was.
        stripped = [
            {name: value for name, value in entry.items() if not name.startswith("quality_")}
            for entry in rows
        ]
        after = {
            entry["model"]: snapshot._winner_key(entry, "bulk") for entry in stripped
        }
        self.assertEqual(before, after)
        # And the winner of the provider is still the larger key: the higher
        # published value wins, whatever the display score of the other row.
        winners, _coverage = snapshot._winners(
            rows,
            {"bulk": [snapshot._key("a", "high"), snapshot._key("a", "low")]},
            aa_cache={"status": "ok"},
        )
        self.assertEqual(winners["bulk"][0]["model"], "high")


class QualityScoreGaugeTests(unittest.TestCase):
    """The gauges carry the integer score and the global rounds, no tier."""

    def samples(self):
        rows = scored(
            [
                row("a", "low", 24.7),
                row("b", "m", 42.7),
                row("c", "top", 45.1),
            ],
            [round_("m", "implementation", "accepted", index=i) for i in range(23)]
            + [round_("m", "cad-execution", "reworked", index=40 + i) for i in range(5)],
        )
        return main.trust_samples({"candidates": rows})

    def test_the_score_gauge_is_83_with_its_basis_and_no_tier(self):
        scores = [
            sample
            for sample in self.samples()
            if sample[0] == "ghostship_ai_model_quality_score"
        ]
        entry = next(
            sample for sample in scores if sample[1]["model"] == "m"
        )
        self.assertEqual(entry[1]["provider"], "b")
        self.assertEqual(entry[1]["basis"], "AA + outcomes")
        self.assertNotIn("tier", entry[1])
        self.assertEqual(entry[2], 83.0)

    def test_the_rounds_gauge_is_28_and_23_and_carries_no_tier(self):
        rounds = [
            sample
            for sample in self.samples()
            if sample[0] == "ghostship_ai_model_quality_rounds"
            and sample[1]["model"] == "m"
        ]
        published = {sample[1]["field"]: sample[2] for sample in rounds}
        self.assertEqual(published, {"n": 28.0, "s": 23.0})
        for sample in rounds:
            self.assertNotIn("tier", sample[1])

    def test_the_help_declares_both_gauges(self):
        self.assertIn("ghostship_ai_model_quality_score", main.METRIC_HELP)
        self.assertIn("ghostship_ai_model_quality_rounds", main.METRIC_HELP)


if __name__ == "__main__":
    unittest.main()
