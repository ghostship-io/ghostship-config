"""The real collector entrypoint, with fake I/O and the real wiring.

These tests call `main.collect` and `main.build_snapshot` through the module's
own names. They exist because unit tests of the builder helpers passed while
the entrypoint crashed: the AA feed has to reach the ranking and the snapshot
through the real signatures, not only through a test helper.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog as catalog_module  # noqa: E402
import main  # noqa: E402
from metrics import SourceResult  # noqa: E402

NOW = 1_800_000_000.0


def fake_aa_cache():
    return {
        "status": "ok",
        "index_version": "4.3",
        "intelligence_index_version": "4.3",
        "fetched_at": "2027-01-15T08:00:00Z",
        "fetched_at_epoch": NOW,
        "records": [
            {
                "id": "id-gpt-6-1-sol-high",
                "slug": "gpt-6-1-sol-high",
                "model": "GPT-6.1 Sol (High)",
                "release_date": "2026-12-01",
                "indices": {"intelligence_index": 50.2},
                "cost_per_task": 0.4,
                "median_performance": 100.0,
                "prices": {},
            },
            {
                "id": "id-gpt-6-1-sol",
                "slug": "gpt-6-1-sol",
                "model": "GPT-6.1 Sol (Max)",
                "release_date": "2026-12-01",
                "indices": {"intelligence_index": 51.8},
                "cost_per_task": 0.4,
                "median_performance": 100.0,
                "prices": {},
            },
        ],
    }


def fake_catalog():
    return catalog_module.Catalog(
        {
            "openai": {
                "models": {
                    "gpt-6.1-sol": {
                        "name": "GPT-6.1 Sol",
                        "family": "gpt-sol",
                        "release_date": "2026-12-01",
                        "modalities": {"input": ["text", "image"]},
                        "cost": {"input": 1.0, "output": 2.0},
                    }
                }
            }
        }
    )


def fake_aa_3d():
    return {
        "status": "ok",
        "benchmark": "AA-3D",
        "fetched_at_epoch": NOW,
        "records": [
            {
                "id": "aa3d-1",
                "slug": "gpt-6-1-sol",
                "model": "GPT-6.1 Sol (Max)",
                "elo": 1118.0,
                "elo_interval": {"low": 1085.0, "high": 1150.0},
                "cost_per_task": None,
                "source": "https://artificialanalysis.ai/evaluations/aa-3d",
                "observed_at": "2026-10-22T00:00:00Z",
            }
        ],
    }


class EntrypointSmokeTests(unittest.TestCase):
    def setUp(self):
        # Every source is faked at the module name `collect` calls.
        def fake_t3(moment, catalog, context):
            context["native_models"] = {
                ("codex", "gpt-6.1-sol"): {
                    "providerInstance": "codex",
                    "modelId": "gpt-6.1-sol",
                    "options": [
                        {
                            "id": "reasoningEffort",
                            "currentValue": "high",
                            "values": ["low", "medium", "high", "max"],
                        }
                    ],
                }
            }
            context["offered_models"] = [("codex", "gpt-6.1-sol")]
            return [
                SourceResult(
                    source="t3",
                    status="ok",
                    reason="ok",
                    observed_at=moment,
                    metrics=[
                        (
                            "ghostship_ai_free_model",
                            {"provider": "codex", "model": "gpt-6.1-sol"},
                            1.0,
                        )
                    ],
                )
            ]

        def empty(*args, **kwargs):
            return SourceResult(source="fake", status="ok", reason="ok", observed_at=NOW)

        self._main = main
        self._originals = {
            "collect_t3": main.collect_t3,
            "grok": main.providers_module.read_grok,
            "go": main.providers_module.read_opencode_go,
            "antigravity": main.providers_module.read_antigravity,
            "openrouter": main.providers_module.read_openrouter,
            "ollama": main.providers_module.read_ollama,
            "pool": main.pool_module.collect,
        }
        main.collect_t3 = fake_t3
        main.providers_module.read_grok = empty
        main.providers_module.read_opencode_go = empty
        main.providers_module.read_antigravity = empty
        main.providers_module.read_openrouter = empty
        main.providers_module.read_ollama = empty
        main.pool_module.collect = lambda *a, **k: []

    def tearDown(self):
        main.collect_t3 = self._originals["collect_t3"]
        main.providers_module.read_grok = self._originals["grok"]
        main.providers_module.read_opencode_go = self._originals["go"]
        main.providers_module.read_antigravity = self._originals["antigravity"]
        main.providers_module.read_openrouter = self._originals["openrouter"]
        main.providers_module.read_ollama = self._originals["ollama"]
        main.pool_module.collect = self._originals["pool"]

    def test_ranking_samples_runs_without_models_and_with_a_feed(self):
        catalog = fake_catalog()
        samples, ranked = main.ranking_samples(
            [], catalog, {}, NOW, aa_cache=fake_aa_cache()
        )
        self.assertIsInstance(ranked, list)
        self.assertIsInstance(samples, list)

    def test_the_feed_reaches_the_ranking_and_the_snapshot(self):
        # The catalog load is the only file the entrypoint reads.
        original_load = main.catalog_module.Catalog.load
        main.catalog_module.Catalog.load = classmethod(lambda cls, path: fake_catalog())
        try:
            results, extra, context = main.collect(
                NOW,
                aa_cache=fake_aa_cache(),
                aa_3d_cache=fake_aa3d_cache(),
            )
        finally:
            main.catalog_module.Catalog.load = original_load
        ranked = context.get("ranked") or []
        workhorse = [entry for entry in ranked if entry.model == "gpt-6.1-sol"]
        self.assertTrue(workhorse)
        self.assertEqual(workhorse[0].quality, 50.2)
        snapshot = main.build_snapshot(
            results,
            ranked,
            context,
            NOW,
            aa_cache=fake_aa_cache(),
            aa_3d_cache=fake_aa3d_cache(),
            catalog=fake_catalog(),
        )
        row = [candidate for candidate in snapshot["candidates"] if candidate["model"] == "gpt-6.1-sol"][0]
        self.assertEqual(row["aa"]["state"], "measured")
        self.assertEqual(row["aa"]["condition"]["variant_match"], "exact")
        self.assertEqual(row["aa"]["condition"]["measured_variant"], "high")
        self.assertEqual(snapshot["aa_coverage"]["states"]["measured"], 1)
        self.assertEqual(row["three_d"]["state"], "measured")
        self.assertEqual(row["value_3d"]["cost_source"], "artificialanalysis_intelligence")

    def test_the_entrypoint_writes_a_snapshot_with_the_feed(self):
        import tempfile

        import json

        with tempfile.TemporaryDirectory() as directory:
            aa_path = Path(directory) / "aa.json"
            aa_path.write_text(json.dumps(fake_aa_cache()))
            aa_3d_path = Path(directory) / "aa3d.json"
            aa_3d_path.write_text(json.dumps(fake_aa3d_cache()))
            original_load = main.catalog_module.Catalog.load
            main.catalog_module.Catalog.load = classmethod(lambda cls, path: fake_catalog())
            try:
                code = main.main(
                    [
                        "--stdout",
                        "--output",
                        str(Path(directory) / "ai-usage.prom"),
                        "--snapshot",
                        str(Path(directory) / "routing.json"),
                        "--projection",
                        str(Path(directory) / "projection.json"),
                        "--state",
                        str(Path(directory) / "state.json"),
                        "--facts",
                        "/dev/null",
                        "--aa-cache",
                        str(aa_path),
                        "--aa-3d-cache",
                        str(aa_3d_path),
                        "--now",
                        str(NOW),
                    ]
                )
            finally:
                main.catalog_module.Catalog.load = original_load
            self.assertEqual(code, 0)
            written = json.loads((Path(directory) / "routing.json").read_text())
            rows = {row["model"]: row for row in written["candidates"]}
            self.assertIn("gpt-6.1-sol", rows)
            self.assertEqual(rows["gpt-6.1-sol"]["aa"]["state"], "measured")
            self.assertEqual(
                rows["gpt-6.1-sol"]["aa"]["condition"]["measured_variant"], "high"
            )
            self.assertEqual(rows["gpt-6.1-sol"]["three_d"]["state"], "measured")
            self.assertEqual(written["aa_coverage"]["states"]["measured"], 1)


def fake_aa3d_cache():
    return fake_aa_3d()


if __name__ == "__main__":
    unittest.main()
