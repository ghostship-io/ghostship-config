"""The one allowed filter: obsolete models, each with its visible reason."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog
import main
import obsolete
import snapshot


class LineageTests(unittest.TestCase):
    def test_dashed_claude_generations_are_one_version(self):
        self.assertEqual(obsolete.lineage("claude-opus-4-5"), ("claude-opus", "", 4, (4, 5)))
        self.assertEqual(obsolete.lineage("claude-opus-5-5"), ("claude-opus", "", 5, (5, 5)))
        # The date suffix is not a variant.
        self.assertEqual(obsolete.lineage("claude-haiku-4-5-20251001"),
                         ("claude-haiku", "", 4, (4, 5)))

    def test_variants_are_kept_apart(self):
        self.assertEqual(obsolete.lineage("gpt-5.6-sol"), ("gpt", "sol", 5, (5, 6)))
        self.assertEqual(obsolete.lineage("gpt-5.4-mini"), ("gpt", "mini", 5, (5, 4)))
        self.assertEqual(obsolete.lineage("deepseek/deepseek-v4.1-flash"),
                         ("deepseek", "flash", 4, (4, 1)))
        self.assertEqual(obsolete.lineage("Qwen/Qwen3.8-Max-Prime"),
                         ("qwen", "max-prime", 3, (3, 8)))

    def test_a_size_suffix_is_not_a_version(self):
        self.assertIsNone(obsolete.lineage("gpt-oss-120b"))
        self.assertEqual(obsolete.lineage("meta/llama-3.3-70b-instruct"),
                         ("llama", "70b-instruct", 3, (3, 3)))


class Catalog:
    def __init__(self, statuses):
        self.statuses = statuses

    def model_status(self, provider, model):
        return self.statuses.get((provider, model), "")


class ClassifyTests(unittest.TestCase):
    def test_older_claude_generations_are_removed_and_the_current_ones_stay(self):
        offered = [
            ("claude", "claude-haiku-4-5"),
            ("claude", "claude-haiku-5-5"),
            ("claude", "claude-opus-4-5"),
            ("claude", "claude-opus-4-6"),
            ("claude", "claude-opus-4-7"),
            ("claude", "claude-opus-4-8"),
            ("claude", "claude-opus-5"),
            ("claude", "claude-opus-5-5"),
            ("claude", "claude-sonnet-4-6"),
            ("claude", "claude-sonnet-5"),
            ("claude", "claude-sonnet-5-5"),
        ]
        records = obsolete.classify(offered)
        self.assertEqual(
            {record["model"] for record in records},
            {
                "claude-haiku-4-5",
                "claude-opus-4-5",
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-opus-4-8",
                "claude-sonnet-4-6",
            },
        )
        for record in records:
            self.assertEqual(record["basis"], "generation")
            self.assertIn("superseded by", record["reason"])
            self.assertIn("claude-", record["superseded_by"])

    def test_a_newer_generation_of_the_same_variant_supersedes(self):
        offered = [
            ("codex", "gpt-5.6-sol"),
            ("codex", "gpt-6-sol"),
            ("codex", "gpt-5.4-mini"),
            ("codex", "gpt-5.6-terra"),
        ]
        records = obsolete.classify(offered)
        self.assertEqual({record["model"] for record in records}, {"gpt-5.6-sol"})
        self.assertEqual(records[0]["superseded_by"], "gpt-6-sol")

    def test_a_plain_generation_is_superseded_by_any_newer_generation(self):
        offered = [
            ("codex", "gpt-5.4"),
            ("codex", "gpt-5.5"),
            ("codex", "gpt-6.1-sol"),
        ]
        records = obsolete.classify(offered)
        self.assertEqual({record["model"] for record in records}, {"gpt-5.4", "gpt-5.5"})
        for record in records:
            self.assertEqual(record["superseded_by"], "gpt-6.1-sol")

    def test_a_different_provider_never_supersedes(self):
        offered = [
            ("commandCode", "claude-opus-4-8"),
            ("claude", "claude-opus-5-5"),
        ]
        self.assertEqual(obsolete.classify(offered), [])

    def test_a_point_release_does_not_hide_the_earlier_generation(self):
        records = obsolete.classify(
            [("claude", "claude-opus-5"), ("claude", "claude-opus-5-5")]
        )
        self.assertEqual(records, [])

    def test_the_catalog_status_is_the_deprecation_reason(self):
        offered = [("opencode", "old-model-free"), ("opencode", "new-model-free")]
        records = obsolete.classify(
            offered, Catalog({("opencode", "old-model-free"): "deprecated"})
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["reason"], "deprecated by the model catalog")
        self.assertEqual(records[0]["basis"], "deprecated")
        self.assertIsNone(records[0]["superseded_by"])

    def test_nothing_else_is_hidden(self):
        offered = [
            ("opencode", "a-free"),
            ("opencode", "b-free"),
            ("openrouter", "c:free"),
            ("codex", "gpt-6.1-sol"),
        ]
        self.assertEqual(obsolete.classify(offered, Catalog({})), [])


class SnapshotTests(unittest.TestCase):
    class Ranked:
        def __init__(self, provider, model):
            self.provider = provider
            self.model = model
            self.tier = "frontier"
            self.rank = 1
            self.score = 100.0
            self.quality = 100.0
            self.remaining = 0.5
            self.expires_in_seconds = 3600.0
            self.available = True
            self.reasons = ("test",)
            self.windows = ()
            self.settled = True
            self.pending_reason = ""
            self.used_tokens = 0.0
            self.three_d_prior = None
            self.three_d_tokens = 0.0
            self.account = provider
            self.pace = None

    def test_the_snapshot_drops_the_obsolete_rows_and_publishes_the_reason(self):
        entries = [
            self.Ranked("claude", "claude-opus-4-8"),
            self.Ranked("claude", "claude-opus-5-5"),
            self.Ranked("codex", "gpt-5.6-sol"),
            self.Ranked("codex", "gpt-6-sol"),
            self.Ranked("cohere", "north-mini-code-1-0"),
        ]
        result = main.build_snapshot(
            [], entries, {"offered_models": [(e.provider, e.model) for e in entries]},
            1_800_000_000.0, catalog=catalog.Catalog({}))
        models = {(row["provider"], row["model"]) for row in result["candidates"]}
        self.assertEqual(
            models,
            {
                ("claude", "claude-opus-5-5"),
                ("codex", "gpt-6-sol"),
                ("cohere", "north-mini-code-1-0"),
            },
        )
        self.assertEqual(
            {(row["provider"], row["model"]) for row in result["obsolete_models"]},
            {("claude", "claude-opus-4-8"), ("codex", "gpt-5.6-sol")},
        )
        self.assertEqual(result["coverage"]["ranking"]["obsolete"], 2)
        self.assertEqual(result["coverage"]["ranking"]["excluded_models"], [])
        for record in result["obsolete_models"]:
            self.assertTrue(record["reason"])
            self.assertTrue(record["superseded_by"])

    def test_pruned_routes_publish_the_obsolete_label_and_reason(self):
        entries = [
            self.Ranked("claude", "claude-opus-4-8"),
            self.Ranked("claude", "claude-opus-5-5"),
        ]
        result = main.build_snapshot(
            [], entries, {"offered_models": [(e.provider, e.model) for e in entries]},
            1_800_000_000.0, catalog=catalog.Catalog({}))
        metrics = main.model_selection.samples(result["model_selection"])
        positions = [(labels, value) for name, labels, value in metrics
                     if name == "ghostship_ai_picker_model_position"]
        pruned = next(labels for labels, _value in positions
                      if labels["model"] == "claude-opus-4-8")
        self.assertEqual(pruned["obsolete"], "true")
        self.assertIn("obsolete", pruned["reason"].lower())
        self.assertEqual(pruned["billing"], "subscription")
        kept = next(labels for labels, _value in positions
                    if labels["model"] == "claude-opus-5-5")
        self.assertEqual(kept["obsolete"], "false")
        selected = [(labels, value) for name, labels, value in metrics
                    if name == "ghostship_ai_picker_model_selected"
                    and labels["model"] == "claude-opus-4-8"]
        self.assertEqual([value for _labels, value in selected], [0.0])

    def test_a_pruned_free_route_keeps_its_free_billing(self):
        entries = [
            self.Ranked("opencode", "old-free"),
            self.Ranked("opencode", "current-free"),
        ]
        document = {"opencode": {"models": {
            "old-free": {"status": "deprecated",
                         "cost": {"input": 0, "output": 0}},
            "current-free": {"cost": {"input": 0, "output": 0}},
        }}}
        result = main.build_snapshot(
            [], entries, {"offered_models": [(e.provider, e.model) for e in entries]},
            1_800_000_000.0, catalog=catalog.Catalog(document),
            free_models={("opencode", "old-free"), ("opencode", "current-free")})
        metrics = main.model_selection.samples(result["model_selection"])
        pruned = next(labels for name, labels, _value in metrics
                      if name == "ghostship_ai_picker_model_position"
                      and labels["model"] == "old-free")
        self.assertEqual(pruned["obsolete"], "true")
        self.assertEqual(pruned["billing"], "free")
        self.assertIn("obsolete", pruned["reason"].lower())


if __name__ == "__main__":
    unittest.main()
