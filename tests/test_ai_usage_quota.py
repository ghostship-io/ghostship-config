"""The quota pace, the frontier membership, and the 3D visual proof.

The pace is the stock client's own line: the share of the window that has
elapsed is the share an even spend would have used. A seven day window that
resets in five days is at 2/7, so an even spend has used 28.57%.
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


quota = load("ai_usage_pace_quota", "quota.py")
ranking = load("ai_usage_pace_ranking", "ranking.py")
snapshot = load("ai_usage_pace_snapshot", "snapshot.py")
threed = load("ai_usage_pace_threed", "threed.py")

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY


def window(used, reset_in=5 * DAY, duration=WEEK, kind="weekly", quota_id="weekly", observed=NOW, **kwargs):
    entry = {
        "kind": kind,
        "quota_id": quota_id,
        "used_ratio": used,
        "reset_epoch": NOW + reset_in,
        "duration_seconds": duration,
        "observed_at": observed,
    }
    entry.update(kwargs)
    return entry


class PaceTests(unittest.TestCase):
    def test_a_seven_day_window_with_five_days_left_is_twenty_eight_percent(self):
        pace = quota.window_pace(window(0.1, reset_in=5 * DAY), NOW)
        self.assertIsNotNone(pace)
        self.assertAlmostEqual(pace["expected_used_ratio"], 2 / 7, places=6)
        self.assertAlmostEqual(pace["pace_delta_ratio"], 2 / 7 - 0.1, places=6)

    def test_a_fresh_window_is_at_zero(self):
        pace = quota.window_pace(window(0.0, reset_in=WEEK), NOW)
        self.assertAlmostEqual(pace["expected_used_ratio"], 0.0, places=6)

    def test_a_window_about_to_reset_is_at_one(self):
        pace = quota.window_pace(window(0.5, reset_in=1.0), NOW)
        self.assertAlmostEqual(pace["expected_used_ratio"], 1.0, places=5)

    def test_a_window_without_a_length_has_no_pace(self):
        self.assertIsNone(quota.window_pace(window(0.1, duration=None), NOW))

    def test_a_window_without_a_reset_has_no_pace(self):
        entry = window(0.1)
        entry["reset_epoch"] = None
        self.assertIsNone(quota.window_pace(entry, NOW))

    def test_a_stale_reading_has_no_pace(self):
        self.assertIsNone(quota.window_pace(window(0.1, observed=NOW - 2 * HOUR), NOW))

    def test_a_reading_from_the_future_has_no_pace(self):
        self.assertIsNone(quota.window_pace(window(0.1, observed=NOW + 2 * HOUR), NOW))

    def test_a_window_already_reset_has_no_pace(self):
        self.assertIsNone(quota.window_pace(window(0.1, reset_in=-HOUR), NOW))

    def test_the_most_constraining_window_is_the_smallest_pace(self):
        # The window with the highest usage and the least remaining is not
        # the most constraining one: the other is further ahead of its own
        # line, so it runs out first.
        lightly_used_but_ahead = window(0.30, reset_in=6 * DAY, quota_id="weekly")
        heavily_used_but_behind = window(0.55, reset_in=1 * DAY, quota_id="weekly-2")
        pace = quota.model_pace(
            [lightly_used_but_ahead, heavily_used_but_behind], NOW
        )
        self.assertEqual(pace["quota"], "weekly")
        self.assertLess(pace["pace_delta_ratio"], 0.0)
        self.assertEqual(pace["used_ratio"], 0.30)

    def test_the_quota_metrics_keep_every_window_apart(self):
        windows = [
            window(0.1, quota_id="weekly", kind="weekly"),
            window(0.2, quota_id="monthly", kind="monthly", duration=30 * DAY, reset_in=20 * DAY),
            window(0.3, quota_id="session", kind="session", duration=5 * HOUR, reset_in=4 * HOUR),
        ]
        samples = quota.quota_pace_samples(windows, NOW)
        quotas = {labels["quota"] for name, labels, _value in samples}
        self.assertEqual(quotas, {"weekly", "monthly", "session"})
        names = {name for name, _labels, _value in samples}
        self.assertEqual(
            names,
            {
                "ghostship_ai_quota_duration_seconds",
                "ghostship_ai_quota_expected_used_ratio",
                "ghostship_ai_quota_pace_delta_ratio",
            },
        )
        for _name, labels, _value in samples:
            self.assertEqual(
                set(labels), {"provider", "account", "model", "window", "quota", "source"}
            )


class FrontierMembershipTests(unittest.TestCase):
    POLICY = {
        "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
        "allowedGptModels": ("gpt-6.1-sol",),
        "backgroundProviderInstances": ("opencode",),
    }

    def _data(self, used):
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord("claude", "claude-opus-5-5"),
                ranking.ModelRecord("codex", "gpt-6.1-sol"),
            ],
            catalog=_Catalog(),
            quota_windows={
                "claude": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=used,
                        reset_epoch=NOW + (2 * DAY if used < 1 else 10 * HOUR),
                        duration_seconds=WEEK,
                        observed_at=NOW,
                    )
                ],
                "codex": [
                    ranking.QuotaWindow(
                        kind="weekly",
                        used_ratio=0.4,
                        reset_epoch=NOW + 5 * DAY,
                        duration_seconds=WEEK,
                        observed_at=NOW,
                    )
                ],
            },
            free_models=set(),
            usage_tokens={},
            now=NOW,
        )
        return snapshot.build_snapshot(
            now=NOW,
            sources=[
                {
                    "id": "t3",
                    "status": "ok",
                    "reason": "ok",
                    "observed_at_epoch": NOW,
                }
            ],
            ranked=ranked,
            native_models={
                ("claude", "claude-opus-5-5"): {
                    "providerInstance": "claudeAgent",
                    "modelId": "claude-opus-5-5",
                    "options": [],
                },
                ("codex", "gpt-6.1-sol"): {
                    "providerInstance": "codex",
                    "modelId": "gpt-6.1-sol",
                    "options": [],
                },
            },
            policy=self.POLICY,
            catalog=_Catalog(),
        )

    def test_a_spent_frontier_model_stays_a_member_with_its_reset(self):
        data = self._data(1.0)
        eligible = {
            entry["model"]: entry for entry in data["coverage"]["frontier"]["eligible"]
        }
        self.assertIn("claude-opus-5-5", eligible)
        claude = eligible["claude-opus-5-5"]
        self.assertEqual(claude["state"], "unavailable")
        self.assertTrue(claude["reset_at"])
        # And it is not a phantom winner: the winner list holds only what can
        # be used now.
        self.assertEqual(data["tiers"]["frontier"], ["codex:gpt-6.1-sol"])

    def test_a_healthy_frontier_model_is_eligible_and_available(self):
        data = self._data(0.2)
        eligible = {
            entry["model"]: entry for entry in data["coverage"]["frontier"]["eligible"]
        }
        self.assertEqual(eligible["claude-opus-5-5"]["state"], "available")
        self.assertIn("claude:claude-opus-5-5", data["tiers"]["frontier"])


class ThreeDVisualTests(unittest.TestCase):
    def test_attachment_alone_is_not_visual_proof(self):
        self.assertFalse(threed.visual_capable({"attachment": True}))

    def test_a_family_name_alone_is_not_visual_proof(self):
        self.assertFalse(threed.visual_capable({"family": "gemini"}))

    def test_the_image_modality_is_proof(self):
        self.assertTrue(threed.visual_capable({"modalities": {"input": ["text", "image"]}}))

    def test_a_text_only_model_is_excluded_even_with_a_high_prior(self):
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("ollama", "text-model")],
            catalog=_TextCatalog(),
            quota_windows={},
            free_models=set(),
            usage_tokens={("ollama", "text-model"): 5_000_000_000.0},
            three_d_scores={
                ("ollama", "text-model"): {
                    "score": 0.95,
                    "prior": 0.95,
                    "usage_tokens": 5_000_000_000.0,
                    "eligible": False,
                }
            },
            now=NOW,
        )
        self.assertFalse(any(entry.tier == "3d" for entry in ranked))

    def test_a_visual_model_with_a_good_prior_qualifies(self):
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("antigravity", "gemini-3.8-flash")],
            catalog=_VisualCatalog(),
            quota_windows={},
            free_models=set(),
            usage_tokens={},
            three_d_scores={
                ("antigravity", "gemini-3.8-flash"): {
                    "score": 0.9,
                    "prior": 0.9,
                    "usage_tokens": 0.0,
                    "eligible": True,
                }
            },
            now=NOW,
        )
        self.assertTrue(any(entry.tier == "3d" for entry in ranked))

    def test_the_3d_score_does_not_use_token_volume(self):
        ranked = ranking.rank_models(
            models=[ranking.ModelRecord("antigravity", "gemini-3.8-flash")],
            catalog=_VisualCatalog(),
            quota_windows={},
            free_models=set(),
            usage_tokens={("antigravity", "gemini-3.8-flash"): 9_000_000_000.0},
            three_d_scores={
                ("antigravity", "gemini-3.8-flash"): {
                    "score": 0.9,
                    "prior": 0.9,
                    "usage_tokens": 9_000_000_000.0,
                    "eligible": True,
                }
            },
            now=NOW,
        )
        three_d = [entry for entry in ranked if entry.tier == "3d"][0]
        # The prior alone, on the 0..100 scale: no usage bonus.
        self.assertAlmostEqual(three_d.score, 90.0, places=3)


class _Catalog:
    document = {
        "anthropic": {
            "models": {
                "claude-opus-5-5": {
                    "name": "Claude Opus 5.5",
                    "family": "claude-opus",
                    "release_date": "2026-12-01",
                    "limit": {"context": 1000000},
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text", "image"]},
                    "cost": {"input": 4.0, "output": 20.0},
                }
            }
        },
        "openai": {
            "models": {
                "gpt-6.1-sol": {
                    "name": "GPT-6.1 Sol",
                    "family": "gpt-sol",
                    "release_date": "2026-12-01",
                    "limit": {"context": 1000000},
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text", "image"]},
                    "cost": {"input": 2.0, "output": 10.0},
                }
            }
        },
    }

    def price_for(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry["cost"] if entry else None

    def model_name(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry["name"] if entry else model

    def model_entry(self, provider, model):
        key = "anthropic" if provider == "claude" else "openai"
        return self.document[key]["models"].get(model)

    def release_date(self, provider, model):
        entry = self.model_entry(provider, model)
        return entry.get("release_date") if entry else None


class _TextCatalog(_Catalog):
    document = {
        "ollama-cloud": {
            "models": {
                "text-model": {
                    "name": "Text Only",
                    "family": "text",
                    "release_date": "2026-12-01",
                    "modalities": {"input": ["text"]},
                    "cost": {"input": 0.1, "output": 0.4},
                }
            }
        }
    }

    def model_entry(self, provider, model):
        return self.document["ollama-cloud"]["models"].get(model)


class _VisualCatalog(_Catalog):
    document = {
        "google": {
            "models": {
                "gemini-3.8-flash": {
                    "name": "Gemini 3.8 Flash",
                    "family": "gemini",
                    "release_date": "2026-12-01",
                    "modalities": {"input": ["text", "image"]},
                    "cost": {"input": 0.1, "output": 0.4},
                }
            }
        }
    }

    def model_entry(self, provider, model):
        return self.document["google"]["models"].get(model)


if __name__ == "__main__":
    unittest.main()
