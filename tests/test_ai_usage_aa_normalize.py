"""The cache normalizer for the real Artificial Analysis client snapshot.

The input is the exact snapshot of the canonical client
(`artificialanalysis-pp-cli language --all --json`): the outer `meta`/`results`
envelope, the free tier, the index version the upstream reported, the per page
pagination, the completeness aggregate, the live read time, and the official
records. Nothing here fetches anything: the normalizer reads one whole
snapshot and writes one cache.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ai_usage_aa_normalize", ROOT / "aa.py")
aa = importlib.util.module_from_spec(spec)
sys.modules["ai_usage_aa_normalize"] = aa
spec.loader.exec_module(aa)

NOW = 1_800_000_000.0


def official_record(name="MiniMax M3.1 Flash", slug="minimax-m3.1-flash", **overrides):
    record = {
        "id": "0b7c4c7e-0000-0000-0000-000000000001",
        "name": name,
        "slug": slug,
        "release_date": "2026-10-19",
        "model_creator": {"id": "creator-uuid", "name": "MiniMax"},
        "evaluations": {
            "artificial_analysis_intelligence_index": 42.0,
            "artificial_analysis_coding_index": 40.0,
            "artificial_analysis_agentic_index": 38.0,
            "artificial_analysis_engineering_index": 41.0,
        },
        "artificial_analysis_intelligence_index_cost": {
            "total_cost": 0.07,
            "cost_per_task": {"total_cost": 0.05},
        },
        "pricing": {
            "price_1m_input_tokens": 0.0,
            "price_1m_output_tokens": 0.0,
            "price_1m_cache_hit_tokens": 0.0,
            "price_1m_cache_write_tokens": 0.0,
        },
        "performance": {
            "median_output_tokens_per_second": 120.0,
            "median_time_to_first_token_seconds": 0.4,
        },
    }
    record.update(overrides)
    return record


def snapshot(records=None, total_pages=2, page_size=2, version=4.3, read_at="2026-10-21T23:06:07.384805706Z", **overrides):
    rows = records if records is not None else [
        official_record(),
        official_record(name="GPT-6.1 Sol", slug="gpt-6.1-sol"),
        official_record(name="Kimi K3", slug="kimi-k3"),
        official_record(name="GLM-5.3", slug="glm-5.3"),
    ]
    pages = [
        {"page": number, "page_size": page_size, "total_pages": total_pages, "has_more": number < total_pages}
        for number in range(1, total_pages + 1)
    ]
    body = {
        "tier": "free",
        "intelligence_index_version": version,
        "pages": pages,
        "completeness": {
            "scope": "all",
            "complete": True,
            "pages_fetched": total_pages,
            "total_pages": total_pages,
            "page_size": page_size,
            "records": len(rows),
            "last_page_has_more": False,
            "requested_first_page": 1,
        },
        "evidence": {
            "source": "live",
            "read_at": read_at,
            "attribution": "Artificial Analysis (https://artificialanalysis.ai/)",
        },
        "data": rows,
    }
    body.update(overrides)
    return {"meta": {"source": "live"}, "results": body}


class NormalizeTests(unittest.TestCase):
    def test_a_complete_free_snapshot_normalizes(self):
        document = aa.normalize(snapshot(), NOW)
        self.assertEqual(document["status"], "ok")
        self.assertEqual(document["tier"], "free")
        self.assertEqual(document["intelligence_index_version"], "4.3")
        self.assertEqual(document["completeness"]["pages_fetched"], 2)
        self.assertEqual(len(document["records"]), 4)

    def test_the_version_comes_from_the_feed(self):
        document = aa.normalize(snapshot(version=4.4), NOW)
        self.assertEqual(document["status"], "ok")
        self.assertEqual(document["intelligence_index_version"], "4.4")

    def test_a_record_keeps_the_official_identity_and_values(self):
        document = aa.normalize(snapshot(), NOW)
        record = document["records"][0]
        self.assertEqual(record["model"], "MiniMax M3.1 Flash")
        self.assertEqual(record["slug"], "minimax-m3.1-flash")
        self.assertEqual(record["provider"], "MiniMax")
        self.assertEqual(record["release_date"], "2026-10-19")
        self.assertEqual(record["indices"]["intelligence_index"], 42.0)
        self.assertEqual(record["prices"]["input"], 0.0)
        self.assertEqual(record["cost_per_task"], 0.05)
        self.assertEqual(record["median_performance"], 120.0)

    def test_a_null_value_is_preserved(self):
        record = official_record(
            evaluations={"artificial_analysis_intelligence_index": None},
            pricing={"price_1m_input_tokens": None},
            performance={"median_output_tokens_per_second": None},
            artificial_analysis_intelligence_index_cost=None,
            release_date=None,
            model_creator=None,
        )
        document = aa.normalize(snapshot(records=[record, official_record()]), NOW)
        self.assertEqual(document["status"], "ok")
        first = document["records"][0]
        self.assertIsNone(first["indices"]["intelligence_index"])
        self.assertIsNone(first["prices"]["input"])
        self.assertIsNone(first["median_performance"])
        self.assertIsNone(first["release_date"])
        self.assertIsNone(first["cost_per_task"])

    def test_a_cost_per_task_is_not_a_token_price(self):
        record = official_record(
            pricing={"price_1m_input_tokens": 0.15, "price_1m_output_tokens": 0.6}
        )
        document = aa.normalize(snapshot(records=[record]), NOW)
        row = document["records"][0]
        self.assertEqual(row["cost_per_task"], 0.05)
        self.assertEqual(row["prices"]["input"], 0.15)

    def test_a_partial_snapshot_is_rejected(self):
        body = snapshot()
        body["results"]["completeness"]["complete"] = False
        self.assertEqual(aa.normalize(body, NOW)["reason"], "incomplete")

    def test_a_page_scope_snapshot_is_rejected(self):
        body = snapshot()
        body["results"]["completeness"]["scope"] = "page"
        self.assertEqual(aa.normalize(body, NOW)["reason"], "incomplete")

    def test_a_snapshot_that_starts_late_is_rejected(self):
        body = snapshot()
        body["results"]["completeness"]["requested_first_page"] = 2
        self.assertEqual(aa.normalize(body, NOW)["reason"], "not_from_the_first_page")

    def test_a_last_page_with_more_is_rejected(self):
        body = snapshot()
        body["results"]["completeness"]["last_page_has_more"] = True
        self.assertEqual(aa.normalize(body, NOW)["reason"], "last_page_still_has_more")

    def test_a_pages_disagreement_is_rejected(self):
        body = snapshot()
        body["results"]["pages"][1]["total_pages"] = 3
        self.assertEqual(aa.normalize(body, NOW)["reason"], "pages_disagree")

    def test_a_missing_page_is_rejected(self):
        body = snapshot()
        body["results"]["pages"] = body["results"]["pages"][:1]
        self.assertEqual(aa.normalize(body, NOW)["reason"], "pages_disagree")

    def test_a_record_count_disagreement_is_rejected(self):
        body = snapshot()
        body["results"]["completeness"]["records"] = 9
        self.assertEqual(aa.normalize(body, NOW)["reason"], "record_count_disagrees")

    def test_a_missing_version_is_rejected(self):
        body = snapshot()
        del body["results"]["intelligence_index_version"]
        self.assertEqual(aa.normalize(body, NOW)["reason"], "no_index_version")

    def test_a_paid_tier_is_rejected(self):
        body = snapshot()
        body["results"]["tier"] = "pro"
        self.assertEqual(aa.normalize(body, NOW)["reason"], "not_the_free_tier")

    def test_a_missing_read_time_is_rejected(self):
        body = snapshot(read_at="")
        self.assertEqual(aa.normalize(body, NOW)["reason"], "no_read_time")

    def test_a_read_time_in_the_future_is_rejected(self):
        body = snapshot(read_at="2027-06-01T00:00:00Z")
        self.assertEqual(aa.normalize(body, NOW)["reason"], "read_time_in_the_future")

    def test_a_non_live_read_is_rejected(self):
        body = snapshot()
        body["meta"]["source"] = "local"
        self.assertEqual(aa.normalize(body, NOW)["reason"], "not_a_live_read")

    def test_the_cli_writes_the_cache_atomically_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "snapshot.json"
            output_path = Path(directory) / "cache.json"
            input_path.write_text(json.dumps(snapshot()))
            code = aa.main(["normalize", "--input", str(input_path), "--output", str(output_path)])
            self.assertEqual(code, 0)
            first = output_path.read_text()
            first_stat = output_path.stat().st_mtime_ns
            # The same snapshot again leaves the cache untouched.
            code = aa.main(["normalize", "--input", str(input_path), "--output", str(output_path)])
            self.assertEqual(code, 0)
            self.assertEqual(output_path.read_text(), first)
            self.assertEqual(output_path.stat().st_mtime_ns, first_stat)
            # And the cache loads under the reader contract, read just after
            # the snapshot was taken.
            read_epoch = aa.load_cache(output_path, NOW + 60)["fetched_at_epoch"]
            cache = aa.load_cache(output_path, read_epoch + 60)
            self.assertEqual(cache["status"], "ok")
            self.assertEqual(cache["index_version"], "4.3")
            self.assertEqual(len(cache["records"]), 4)
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o644)

    def test_the_cli_refuses_a_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "snapshot.json"
            output_path = Path(directory) / "cache.json"
            body = snapshot()
            body["results"]["completeness"]["complete"] = False
            input_path.write_text(json.dumps(body))
            code = aa.main(["normalize", "--input", str(input_path), "--output", str(output_path)])
            self.assertEqual(code, 2)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
