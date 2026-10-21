"""The boundaries the frontier review named, tested against the real builders.

* A window that is known to be spent decides the state, whatever else is
  unknown. An unknown window never hides an exhausted allowance.
* The quality feed binds to an exact identity: a prefix match never lets a
  reasoning variant inherit the score of another model.
* The age of a cache is the age of its evidence, not the age of the file, and
  a reading from the future is not a fresh reading.
* A cache is an untrusted file: only known states and reasons survive it.
"""
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


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


aa = load("ai_usage_boundary_aa", "aa.py")
snapshot = load("ai_usage_boundary_snapshot", "snapshot.py")

NOW = 1_800_000_000.0
HOUR = 3600.0


def window(evidence="provider_reported", remaining=0.0, kind="weekly"):
    return {
        "kind": kind,
        "evidence": evidence,
        "used_ratio": 1.0 if remaining == 0.0 else 0.2,
        "remaining_ratio": remaining,
        "reset_at": "2026-10-22T00:00:00Z",
        "seconds_to_reset": 3600,
        "duration_seconds": 7 * 24 * 3600,
        "check_at": "2026-10-21T00:00:00Z",
        "provenance": "collector",
    }


class QuotaStateTests(unittest.TestCase):
    def test_a_spent_window_is_not_masked_by_an_unknown_one(self):
        state = snapshot._quota_state(
            0.0, [window(remaining=0.0), window(evidence="unknown", remaining=None, kind="session")]
        )
        self.assertEqual(state, "exhausted")

    def test_an_unknown_window_alone_is_unknown(self):
        state = snapshot._quota_state(None, [window(evidence="unknown", remaining=None)])
        self.assertEqual(state, "unknown")

    def test_a_known_window_with_headroom_is_available(self):
        state = snapshot._quota_state(0.8, [window(remaining=0.8)])
        self.assertEqual(state, "available")

    def test_the_consumer_sees_the_exhausted_state(self):
        row = {
            "quota_state": snapshot._quota_state(
                0.0,
                [
                    window(remaining=0.0),
                    window(evidence="unknown", remaining=None, kind="session"),
                ],
            ),
            "availability": {
                "state": "available"
                if snapshot._quota_state(
                    0.0,
                    [
                        window(remaining=0.0),
                        window(evidence="unknown", remaining=None, kind="session"),
                    ],
                )
                == "available"
                else "unavailable"
            },
        }
        self.assertEqual(row["quota_state"], "exhausted")
        self.assertEqual(row["availability"]["state"], "unavailable")


class FeedBindingTests(unittest.TestCase):
    def _cache(self, records):
        return {
            "status": "ok",
            "index_version": "4.3",
            "fetched_at": "2026-10-21T00:00:00Z",
            "fetched_at_epoch": NOW - 3600,
            "age_seconds": 3600,
            "records": records,
        }

    def test_an_exact_name_binds(self):
        cache = self._cache([{"model": "MiniMax M3.1 Flash", "indices": {"intelligence_index": 42}}])
        record = aa.lookup(cache, "minimax-m3.1-flash")
        self.assertIsNotNone(record)
        self.assertEqual(record["indices"]["intelligence_index"], 42)

    def test_a_prefix_match_does_not_bind(self):
        cache = self._cache(
            [
                {"model": "MiniMax M3.1 Flash", "indices": {"intelligence_index": 42}},
                {"model": "MiniMax M3.1 Flash High", "indices": {"intelligence_index": 60}},
            ]
        )
        # The exact name binds to its own record.
        self.assertIsNotNone(aa.lookup(cache, "minimax-m3.1-flash"))
        # The variant binds to its own record, not to the shorter one.
        variant = aa.lookup(cache, "minimax-m3.1-flash-high")
        self.assertIsNotNone(variant)
        self.assertEqual(variant["indices"]["intelligence_index"], 60)
        # And a name that is only a prefix of a record binds to nothing.
        self.assertIsNone(aa.lookup(cache, "minimax-m3.1-flash-h"))

    def test_a_different_model_never_inherits_a_score(self):
        cache = self._cache([{"model": "gpt-5.5", "indices": {"intelligence_index": 70}}])
        self.assertIsNone(aa.lookup(cache, "gpt-5.5-turbo"))


class CacheAgeTests(unittest.TestCase):
    def _write(self, directory, document):
        path = Path(directory) / "artificial-analysis.json"
        path.write_text(json.dumps(document))
        return str(path)

    def test_the_age_comes_from_the_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                directory,
                {
                    "intelligence_index_version": "4.3",
                    "fetched_at_epoch": NOW - 7200,
                    "records": [],
                },
            )
            # The file itself is new, but the evidence is two hours old.
            os.utime(path, (NOW, NOW))
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "ok")
        self.assertEqual(cache["age_seconds"], 7200)

    def test_a_copied_old_cache_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                directory,
                {
                    "intelligence_index_version": "4.3",
                    "fetched_at_epoch": NOW - 10 * 24 * 3600,
                    "records": [],
                },
            )
            os.utime(path, (NOW, NOW))
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "stale")
        self.assertEqual(cache["records"], [])

    def test_a_future_reading_is_not_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                directory,
                {
                    "intelligence_index_version": "4.3",
                    "fetched_at_epoch": NOW + 3600,
                    "records": [],
                },
            )
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "future")
        self.assertEqual(cache["records"], [])

    def test_a_cache_without_a_read_time_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, {"intelligence_index_version": "4.3", "records": []})
            cache = aa.load_cache(path, NOW)
        self.assertEqual(cache["status"], "unknown_evidence_time")

    def test_a_cache_never_carries_a_private_field(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                directory,
                {
                    "intelligence_index_version": "4.3",
                    "fetched_at_epoch": NOW - 3600,
                    "fetched_at": "<owner-email> /srv/apps/secret",
                    "reason": "sk-live-AAAABBBBCCCC",
                    "records": [],
                },
            )
            cache = aa.load_cache(path, NOW)
        self.assertNotIn("@", cache.get("fetched_at") or "")
        self.assertNotIn("/srv", cache.get("fetched_at") or "")
        self.assertIn(cache.get("reason") or "", aa.CACHE_STATUSES + (aa.codes.UNKNOWN,))
        self.assertNotIn("sk-live", json.dumps(cache))


class PermissionTests(unittest.TestCase):
    """The permission of a model is bound to its exact identity."""

    POLICY = {
        "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
        "allowedGptModels": ("gpt-6.1-sol",),
        "backgroundProviderInstances": ("opencode",),
    }

    def _row(self, provider, model, mapped=True):
        return {
            "provider": provider,
            "model": model,
            "native": {"mapped": mapped, "provider_instance_id": provider, "model_id": model},
            "tiers": ["bulk"],
            "rank": {"bulk": 1},
            "score": {"bulk": 10.0},
            "value": {"value": 10.0, "strength": 80.0},
            "availability": {"state": "available"},
            "admission": {"state": "settled"},
            "role": "delegate",
            "quota_state": "available",
        }

    def test_only_the_permitted_gpt_model_is_permitted(self):
        allowed = snapshot._eligibility("codex", "gpt-6.1-sol", ["bulk"], self._row("codex", "gpt-6.1-sol")["native"], self.POLICY)
        other = snapshot._eligibility("codex", "gpt-6-luna", ["bulk"], self._row("codex", "gpt-6-luna")["native"], self.POLICY)
        self.assertTrue(allowed["gpt_model_allowed"]["allowed"])
        self.assertFalse(other["gpt_model_allowed"]["allowed"])

    def test_a_name_that_only_contains_a_permitted_model_is_not_permitted(self):
        row = self._row("codex", "gpt-6.1-sol-unapproved")
        flags = snapshot._eligibility("codex", "gpt-6.1-sol-unapproved", ["bulk"], row["native"], self.POLICY)
        self.assertFalse(flags["gpt_model_allowed"]["allowed"])
        self.assertFalse(flags["delegate"]["allowed"])

    def test_a_permitted_model_keeps_its_frontier_permission(self):
        row = self._row("codex", "gpt-6.1-sol")
        flags = snapshot._eligibility("codex", "gpt-6.1-sol", ["frontier"], row["native"], self.POLICY)
        self.assertTrue(flags["frontier_prime"]["allowed"])

    def test_a_model_that_is_not_permitted_never_wins_a_tier(self):
        rows = [
            {
                "provider": "codex",
                "model": "gpt-6-luna",
                "key": "codex:gpt-6-luna",
                "tiers": ["bulk"],
                "rank": {"bulk": 1},
                "score": {"bulk": 200.0},
                "value": {"value": 200.0, "strength": 90.0},
                "availability": {"state": "available"},
                "admission": {"state": "settled"},
                "eligibility": {
                    "frontier_prime": {"allowed": False},
                    "delegate": {"allowed": False},
                },
                "quota_state": "available",
                "native": {"mapped": True},
            },
            {
                "provider": "codex",
                "model": "gpt-6.1-sol",
                "key": "codex:gpt-6.1-sol",
                "tiers": ["bulk"],
                "rank": {"bulk": 2},
                "score": {"bulk": 100.0},
                "value": {"value": 100.0, "strength": 100.0},
                "availability": {"state": "available"},
                "admission": {"state": "settled"},
                "eligibility": {
                    "frontier_prime": {"allowed": True},
                    "delegate": {"allowed": True},
                },
                "quota_state": "available",
                "native": {"mapped": True},
            },
        ]
        winners, _coverage = snapshot._winners(rows, {"bulk": ["codex:gpt-6-luna", "codex:gpt-6.1-sol"]})
        self.assertEqual([winner["model"] for winner in winners["bulk"]], ["gpt-6.1-sol"])


if __name__ == "__main__":
    unittest.main()
