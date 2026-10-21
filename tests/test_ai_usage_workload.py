"""The workload policy, the free role cap, and the quality feed."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_workload", ROOT / "snapshot.py")
snapshot = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_workload"] = snapshot
spec.loader.exec_module(snapshot)

spec = importlib.util.spec_from_file_location("ai_usage_aa", ROOT / "aa.py")
aa = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_aa"] = aa
spec.loader.exec_module(aa)

NOW = 1_800_000_000.0


def Row(provider, model, tier, mapped=True, instance="opencode", score=50.0, available=True):
    """A candidate row, shaped like the snapshot's own."""
    return {
        "provider": provider,
        "model": model,
        "tiers": [tier],
        "rank": {tier: 1},
        "score": {tier: score},
        "available": available,
        "availability": {"state": "available" if available else "unavailable"},
        "admission": {"state": "settled", "reason": ""},
        "native": {
            "provider_instance_id": instance if mapped else None,
            "model_id": model if mapped else None,
            "options": [],
            "mapped": mapped,
        },
        "role": "prime" if tier == "frontier" else "delegate",
        "quota_state": "available",
    }


def rows():
    return [
        Row("opencode-go", "minimax-m3.1-flash-free", "free", mapped=True, instance="opencode"),
        Row("kilo", "kimi-k3", "free", mapped=False, instance=None),
        Row("codex", "gpt-6.1-sol", "frontier", mapped=True, instance="codex", score=90.0),
        Row("ollama", "deepseek-v4.1-flash", "bulk", mapped=True, instance="opencode", score=40.0),
    ]


class WorkloadTests(unittest.TestCase):
    def test_research_takes_a_free_route(self):
        result = snapshot._recommendations(rows(), snapshot.WORKLOAD_CLASSES)
        self.assertEqual(result["research"]["tier"], "free")
        self.assertTrue(result["research"]["delegate"])

    def test_a_pool_route_may_do_research_but_is_not_a_delegate(self):
        result = snapshot._recommendations(rows(), snapshot.WORKLOAD_CLASSES)
        research = result["research"]
        if research["native"]["mapped"] is False:
            self.assertFalse(research["delegate"])
            self.assertIn("read only", research["reason"])

    def test_the_review_never_takes_a_free_route(self):
        result = snapshot._recommendations(rows(), snapshot.WORKLOAD_CLASSES)
        self.assertNotEqual(result["review"]["tier"], "free")
        self.assertEqual(result["review"]["role"], "prime")

    def test_engineering_never_takes_a_free_route(self):
        result = snapshot._recommendations(rows(), snapshot.WORKLOAD_CLASSES)
        self.assertNotEqual(result["engineering"]["tier"], "free")

    def test_a_class_without_a_free_route_says_so(self):
        paid_only = [Row("codex", "gpt-6.1-sol", "frontier", mapped=True, instance="codex")]
        result = snapshot._recommendations(paid_only, snapshot.WORKLOAD_CLASSES)
        self.assertEqual(result["research"]["tier"], "frontier")
        self.assertIn("no free route", result["research"]["reason"])

    def test_the_complexity_ceiling_is_independent_of_the_quality(self):
        for entry in snapshot.WORKLOAD_CLASSES:
            if entry["complexity"] == "high":
                self.assertFalse(entry["free_eligible"])


class QualityFeedTests(unittest.TestCase):
    def _cache(self, directory, **overrides):
        document = {
            "intelligence_index_version": "4.3",
            "fetched_at": "2026-10-21T00:00:00Z",
            "fetched_at_epoch": NOW - 3600,
            "records": [
                {
                    "model": "MiniMax M3.1 Flash",
                    "provider": "minimax",
                    "release_date": "2026-10-19",
                    "indices": {"intelligence_index": 42.0, "coding_index": 40.0},
                    "prices": {"input": 0.0, "output": 0.0, "cache_read": 0.0},
                    "cost_per_task": 0.0,
                    "median_performance": 120.0,
                }
            ],
        }
        document.update(overrides)
        path = Path(directory) / "artificial-analysis.json"
        path.write_text(json.dumps(document))
        # The file was read an hour ago.
        os.utime(path, (NOW - 3600, NOW - 3600))
        return str(path)

    def test_a_fresh_cache_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._cache(directory)
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(cache["index_version"], "4.3")

    def test_a_missing_cache_is_a_coverage_gap(self):
        cache = aa.load_cache("/nonexistent/artificial-analysis.json", NOW)
        self.assertEqual(cache["status"], "missing")
        self.assertEqual(cache["records"], [])

    def test_a_cache_of_another_index_version_is_not_mixed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._cache(directory, intelligence_index_version="3.9")
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "incompatible")
        self.assertEqual(cache["records"], [])

    def test_a_stale_cache_is_a_coverage_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._cache(directory)
            cache = aa.load_cache(path, NOW + 10 * 24 * 3600)
        self.assertEqual(cache["status"], "stale")

    def test_a_model_the_feed_does_not_list_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._cache(directory)
            cache = aa.load_cache(path, NOW)
        self.assertIsNone(aa.lookup(cache, "some-model-nobody-knows"))

    def test_the_record_keeps_the_version_and_the_fetch_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._cache(directory)
            cache = aa.load_cache(path, NOW)
            record = aa.lookup(cache, "minimax-m3.1-flash")
        self.assertEqual(record["index_version"], "4.3")
        self.assertEqual(record["fetched_at"], "2026-10-21T00:00:00Z")
        self.assertEqual(record["source"], "artificialanalysis")

    def test_a_cost_per_task_is_not_a_token_price(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._cache(directory)
            cache = aa.load_cache(path, NOW)
            record = aa.lookup(cache, "minimax-m3.1-flash")
        # The cost per task and the token price are different things: the
        # first is what a measured task costs, the second what a million
        # tokens cost.
        self.assertEqual(record["cost_per_task"], 0.0)
        self.assertEqual(record["prices"]["input"], 0.0)
        self.assertEqual(record["median_performance"], 120.0)
        # The feed reports the two separately; the collector never turns
        # one into the other.


if __name__ == "__main__":
    unittest.main()
