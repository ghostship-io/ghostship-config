"""Only the best proven free route per provider keeps a T3 native identity."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import os
import tempfile
from unittest.mock import patch

import catalog
import main
import tool_loop_evidence


class Ranked:
    def __init__(self, provider, model, quality, rank=1):
        self.provider = provider
        self.model = model
        self.tier = "free"
        self.rank = rank
        self.score = quality
        self.quality = quality
        self.remaining = 0.8
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


def approved(*pairs):
    return {"policy": {"model_selection": {"approved_free_workers": [
        {"provider": provider, "model": model,
         "allow_training": True, "sensitivity": ["public", "internal"]}
        for provider, model in pairs
    ]}}}


def proof(provider, model):
    return {"schema_version": 1, "source": "probe", "passed": True,
            "provider": "opencode-free", "model": f"{provider}/{model}",
            "id": f"probe:{provider}:{model}", "date": 1_800_000_000.0,
            "kind": "code", "task": "t3-tool-loop", "effort": "default"}


class BestFreeTests(unittest.TestCase):
    def test_at_most_the_two_highest_quality_proven_routes_per_provider(self):
        ranked = [
            Ranked("opencode-free", "google/gemini-3.8-flash", 60),
            Ranked("opencode-free", "google/gemini-3.5-flash-lite", 50),
            Ranked("opencode-free", "google/older", 40),
            Ranked("opencode-free", "nvidia/z-ai/glm-5.3", 89),
            Ranked("opencode-free", "nvidia/z-ai/glm-5.3-flash", 83),
            Ranked("opencode-free", "nvidia/third", 78),
            Ranked("opencode-free", "example-b/qwen/qwen3.8-27b", 73),
            Ranked("opencode-free", "example-a/@cf/google/gemma", 52),
        ]
        outcomes = approved(
            ("google", "gemini-3.8-flash"), ("google", "gemini-3.5-flash-lite"),
            ("google", "older"), ("nvidia", "z-ai/glm-5.3"),
            ("nvidia", "z-ai/glm-5.3-flash"), ("nvidia", "third"),
            ("example-b", "qwen/qwen3.8-27b"),
            ("example-a", "@cf/google/gemma"),
        )
        evidence = [proof(*pair) for pair in (
            ("google", "gemini-3.8-flash"), ("google", "gemini-3.5-flash-lite"),
            ("google", "older"), ("nvidia", "z-ai/glm-5.3"),
            ("nvidia", "z-ai/glm-5.3-flash"), ("nvidia", "third"),
            ("example-b", "qwen/qwen3.8-27b"),
        )]
        best = main.best_free_t3_models(ranked, outcomes, evidence)
        self.assertEqual(best, {
            "google/gemini-3.8-flash", "google/gemini-3.5-flash-lite",
            "nvidia/z-ai/glm-5.3", "nvidia/z-ai/glm-5.3-flash",
            "example-b/qwen/qwen3.8-27b",
        })

    def test_rank_not_quality_decides_the_top_two(self):
        ranked = [
            Ranked("opencode-free", "google/high-quality", 99, rank=5),
            Ranked("opencode-free", "google/best-rank", 10, rank=1),
            Ranked("opencode-free", "google/second-rank", 20, rank=2),
        ]
        outcomes = approved(
            ("google", "high-quality"), ("google", "best-rank"), ("google", "second-rank"))
        evidence = [proof("google", model) for model in
                    ("high-quality", "best-rank", "second-rank")]
        best = main.best_free_t3_models(ranked, outcomes, evidence)
        self.assertEqual(best, {"google/best-rank", "google/second-rank"})

    def test_an_unproven_provider_contributes_no_t3_route(self):
        ranked = [Ranked("opencode-free", "example-a/@cf/google/gemma", 52)]
        best = main.best_free_t3_models(
            ranked,
            approved(("example-a", "@cf/google/gemma")),
            [],
        )
        self.assertEqual(best, set())

    def test_an_unreadable_store_keeps_the_native_mapping(self):
        ranked = [Ranked("opencode-free", "google/gemini-3.8-flash", 60)]
        native = {("opencode-free", "google/gemini-3.8-flash"): {
            "providerInstance": "opencode-free", "modelId": "google/gemini-3.8-flash",
            "available": True}}
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                    "GHOSTSHIP_MODEL_EVIDENCE_PATH": str(Path(directory) / "missing.jsonl")}):
                snapshot = main.build_snapshot(
                    [], ranked,
                    {"offered_models": [(r.provider, r.model) for r in ranked],
                     "native_models": native},
                    1_800_000_000.0, catalog=catalog.Catalog({}),
                    outcomes=approved(("google", "gemini-3.8-flash")))
        row = next(row for row in snapshot["candidates"]
                   if row["model"] == "google/gemini-3.8-flash")
        self.assertTrue(row["native"]["mapped"])
        self.assertEqual(snapshot["tool_loop_evidence"]["state"], "unreadable")

    def test_a_readable_empty_store_is_not_a_proof(self):
        ranked = [Ranked("opencode-free", "google/gemini-3.8-flash", 60)]
        native = {("opencode-free", "google/gemini-3.8-flash"): {
            "providerInstance": "opencode-free", "modelId": "google/gemini-3.8-flash",
            "available": True}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.jsonl"
            path.write_text("")
            with patch.dict(os.environ, {"GHOSTSHIP_MODEL_EVIDENCE_PATH": str(path)}):
                snapshot = main.build_snapshot(
                    [], ranked,
                    {"offered_models": [(r.provider, r.model) for r in ranked],
                     "native_models": native},
                    1_800_000_000.0, catalog=catalog.Catalog({}),
                    outcomes=approved(("google", "gemini-3.8-flash")))
        row = next(row for row in snapshot["candidates"]
                   if row["model"] == "google/gemini-3.8-flash")
        self.assertFalse(row["native"]["mapped"])
        self.assertEqual(snapshot["tool_loop_evidence"]["state"], "empty")

    def test_the_native_identity_is_removed_from_the_non_best_routes(self):
        ranked = [
            Ranked("opencode-free", "google/gemini-3.8-flash", 60),
            Ranked("opencode-free", "google/gemini-3.5-flash-lite", 50),
            Ranked("opencode-free", "google/older", 40),
        ]
        native = {
            ("opencode-free", "google/gemini-3.8-flash"): {
                "providerInstance": "opencode-free", "modelId": "google/gemini-3.8-flash",
                "available": True},
            ("opencode-free", "google/gemini-3.5-flash-lite"): {
                "providerInstance": "opencode-free", "modelId": "google/gemini-3.5-flash-lite",
                "available": True},
            ("opencode-free", "google/older"): {
                "providerInstance": "opencode-free", "modelId": "google/older",
                "available": True},
        }
        outcomes = approved(
            ("google", "gemini-3.8-flash"), ("google", "gemini-3.5-flash-lite"),
            ("google", "older"),
        )
        evidence = [proof("google", model) for model in
                    ("gemini-3.8-flash", "gemini-3.5-flash-lite", "older")]
        snapshot = main.build_snapshot(
            [], ranked, {"offered_models": [(r.provider, r.model) for r in ranked],
                         "native_models": native},
            1_800_000_000.0, catalog=catalog.Catalog({}),
            outcomes=outcomes, model_evidence=evidence,
            tool_loop_proofs=evidence)
        rows = {(row["model"]): row for row in snapshot["candidates"]
                if row["provider"] == "opencode-free"}
        self.assertTrue(rows["google/gemini-3.8-flash"]["native"]["mapped"])
        self.assertTrue(rows["google/gemini-3.5-flash-lite"]["native"]["mapped"])
        self.assertFalse(rows["google/older"]["native"]["mapped"])


class EvidenceReaderTests(unittest.TestCase):
    def write(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "model-evidence.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows))
        return path

    def test_the_latest_event_per_route_wins_and_a_failure_revokes(self):
        now = 1_800_100_000.0
        base = {"schema_version": 1, "kind": "code", "id": "x", "task": "t",
                "effort": "default", "merged": None, "wall_seconds": None,
                "tokens": None, "quota_delta": None, "cost": None,
                "diff_lines": None, "reason": None, "reason_detail": None}
        path = self.write([
            {**base, "source": "probe", "provider": "opencode-free",
             "model": "google/gemini-3.8-flash", "passed": True, "date": now - 60},
            {**base, "source": "probe", "provider": "opencode-free",
             "model": "example-a/@cf/x", "passed": True, "date": now - 60},
            {**base, "source": "probe", "provider": "opencode-free",
             "model": "example-a/@cf/x", "passed": False,
             "reason": "provider_schema", "date": now - 30},
            {**base, "source": "probe", "provider": "opencode-free",
             "model": "opencode/old", "passed": True, "date": now - 40 * 86400},
        ])
        rows = {row["model"]: row for row in tool_loop_evidence.read(now, path)}
        self.assertEqual(rows["google/gemini-3.8-flash"]["state"], "proven")
        self.assertEqual(rows["example-a/@cf/x"]["state"], "failed")
        self.assertNotIn("opencode/old", rows)

    def test_a_failed_probe_is_not_a_best_route(self):
        now = 1_800_100_000.0
        path = self.write([{
            "schema_version": 1, "source": "probe", "kind": "code", "id": "x",
            "task": "t", "provider": "opencode-free", "model": "google/gemini-3.8-flash",
            "effort": "default", "passed": False, "reason": "provider_schema",
            "date": now - 30, "merged": None, "wall_seconds": None, "tokens": None,
            "quota_delta": None, "cost": None, "diff_lines": None, "reason_detail": None}])
        proofs = tool_loop_evidence.read(now, path)
        ranked = [Ranked("opencode-free", "google/gemini-3.8-flash", 60)]
        best = main.best_free_t3_models(
            ranked, approved(("google", "gemini-3.8-flash")), proofs)
        self.assertEqual(best, set())


if __name__ == "__main__":
    unittest.main()
