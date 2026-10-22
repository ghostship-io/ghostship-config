"""The Artificial Analysis public pull: the pages, the records and the diff.

The fixtures are the real pages the pull read, and the real snapshot it
built from them. The tests therefore reproduce the real naming differences
and the real cost per task of the published models.
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aa  # noqa: E402
import aa_diff  # noqa: E402
import aa_pull  # noqa: E402

NOW = 1_800_000_000.0
RAW = Path("/tmp/aa-pull/raw")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def page(name):
    """One real page, or an empty string when it is not there."""
    path = RAW / name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


class PublicPullTests(unittest.TestCase):
    """The pull reads the public pages and builds the cache contract."""

    def test_the_leaderboard_gives_the_scored_models(self):
        rows = aa_pull.parse_leaderboard(page("models_leaderboards.html"))
        self.assertTrue(rows)
        grok = rows.get("grok-4-7")
        self.assertIsNotNone(grok)
        self.assertAlmostEqual(grok["intelligence"], 46.4465506302286, places=6)
        self.assertAlmostEqual(grok["cost_per_task"], 3.738325952106939, places=6)

    def test_the_models_page_gives_the_releases_and_the_variants(self):
        models = aa_pull.parse_models(page("models.html"))
        self.assertTrue(models)
        grok = models.get("grok-4-7")
        self.assertIsNotNone(grok)
        self.assertEqual(grok["reasoning"], "Xhigh")
        self.assertIsNotNone(grok["release_date"])

    def test_the_aa3d_page_gives_the_elo(self):
        board = aa_pull.parse_aa3d(page("aa3d.html"))
        self.assertTrue(board)
        self.assertTrue(any(entry.get("elo") for entry in board.values()))

    def test_the_pull_builds_the_cache_contract(self):
        document = aa_pull.pull(
            read=lambda url: {
                "url": url,
                "http_status": 200,
                "bytes": 10,
                "blocked": False,
                "error": None,
                "text": _page_for(url),
            }
        )
        self.assertEqual(document["status"], "ok")
        self.assertTrue(document["records"])
        record = next(
            entry for entry in document["records"] if entry["slug"] == "grok-4-7"
        )
        self.assertEqual(record["model"], "Grok 4.7 (Xhigh)")
        self.assertAlmostEqual(
            record["indices"]["intelligence_index"], 46.4465506302286, places=6
        )
        self.assertAlmostEqual(record["cost_per_task"], 3.738325952106939, places=6)
        self.assertEqual(record["cost_basis"], aa_pull.COST_BASIS_PUBLISHED)
        # The cache contract the collector reads.
        self.assertEqual(document["intelligence_index_version"], aa.INTELLIGENCE_INDEX_VERSION)
        self.assertIsNotNone(document["fetched_at_epoch"])

    def test_a_blocked_page_keeps_the_last_good_snapshot(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "aa.json"
            cache.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "intelligence_index_version": "4.3",
                        "fetched_at_epoch": NOW - 200000,
                        "records": [{"slug": "kept", "model": "Kept"}],
                    }
                ),
                encoding="utf-8",
            )
            result = aa_pull.refresh(
                cache,
                now=NOW,
                read=lambda url: {
                    "url": url,
                    "http_status": 403,
                    "bytes": 0,
                    "blocked": True,
                    "error": "HTTP 403",
                },
            )
            self.assertEqual(result["status"], "blocked")
            # The last good snapshot is still there.
            self.assertIn("kept", cache.read_text(encoding="utf-8"))

    def test_a_fresh_cache_is_left_alone(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "aa.json"
            cache.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "intelligence_index_version": "4.3",
                        "fetched_at_epoch": NOW - 60,
                        "records": [{"slug": "kept", "model": "Kept"}],
                    }
                ),
                encoding="utf-8",
            )
            result = aa_pull.refresh(cache, now=NOW)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["changed"])

    def test_the_diff_names_the_new_and_the_changed_models(self):
        old = {
            "records": [
                {
                    "slug": "a",
                    "model": "A",
                    "indices": {"intelligence_index": 10.0},
                    "cost_per_task": 1.0,
                },
                {
                    "slug": "b",
                    "model": "B",
                    "indices": {"intelligence_index": 20.0},
                    "cost_per_task": 2.0,
                },
            ]
        }
        new = {
            "records": [
                {
                    "slug": "a",
                    "model": "A",
                    "indices": {"intelligence_index": 11.0},
                    "cost_per_task": 1.0,
                },
                {
                    "slug": "c",
                    "model": "C",
                    "indices": {"intelligence_index": 30.0},
                    "cost_per_task": 3.0,
                },
            ]
        }
        difference = aa_diff.diff(old, new)
        self.assertTrue(difference["has_new_models"])
        self.assertTrue(difference["has_changed_models"])
        self.assertEqual([entry["slug"] for entry in difference["added"]], ["c"])
        self.assertIn("a", difference["changed"])
        self.assertIn("intelligence_index", difference["changed"]["a"]["differences"])

    def test_the_published_cost_of_a_model_page_is_used_as_published(self):
        # The model page publishes the cost per task in its own text.
        text = (
            "<p>On average, it costs $1.48 per task to evaluate Grok 4.6 (High) "
            "on the Intelligence Index.</p>"
        )
        self.assertAlmostEqual(aa_pull._cost_in_text(text), 1.48, places=6)

    def _deprecated_records(self, count=53):
        """The records of the models the leaderboard does not carry."""
        records = {}
        for index in range(count):
            slug = f"deprecated-{index}"
            records[slug] = {
                "id": f"id-{slug}",
                "slug": slug,
                "model": f"Deprecated {index}",
                "release_date": "2026-01-20",
                "indices": {"intelligence_index": 40.0},
                "cost_per_task": None,
                "median_performance": 100.0,
                "prices": {},
                "deprecated": True,
            }
        return records

    def test_the_model_pages_are_read_once_for_the_models_the_catalog_offers(self):
        # A model page is four megabytes. The pull reads the pages of the
        # models the live catalog still offers, and it reads each of them
        # once: the cost of a deprecated model never changes.
        calls: list[str] = []

        def model_page(slug):
            calls.append(slug)
            return {
                "url": f"https://artificialanalysis.ai/models/{slug}",
                "http_status": 200,
                "bytes": 10,
                "blocked": False,
                "error": None,
                "text": (
                    f"<p>On average, it costs $1.00 per task to evaluate "
                    f"Model {slug} on the Intelligence Index.</p>"
                ),
            }

        records = self._deprecated_records()
        # The catalog offers three of them.
        offered = [f"deprecated-{index}" for index in range(3)]

        costs, fetches = aa_pull._read_model_pages(
            records, {}, model_pages=model_page, offered=offered
        )
        self.assertEqual(fetches, 3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(records["deprecated-0"]["cost_per_task"], 1.0)
        self.assertEqual(
            records["deprecated-0"]["cost_basis"], aa_pull.COST_BASIS_MODEL_PAGE
        )
        # The fifty models nobody offers are not read at all.
        self.assertIsNone(records["deprecated-3"]["cost_per_task"])

        # The second run reads nothing: the costs are known.
        again, second_fetches = aa_pull._read_model_pages(
            self._deprecated_records(),
            {},
            model_pages=model_page,
            offered=offered,
            known=costs,
        )
        self.assertEqual(second_fetches, 0)
        self.assertEqual(len(calls), 3)
        self.assertEqual(again["deprecated-0"]["cost"], 1.0)

    def test_a_model_that_is_not_deprecated_is_read_again_at_most_weekly(self):
        calls: list[str] = []

        def model_page(slug):
            calls.append(slug)
            return {
                "url": f"https://artificialanalysis.ai/models/{slug}",
                "http_status": 200,
                "bytes": 10,
                "blocked": False,
                "error": None,
                "text": (
                    "<p>On average, it costs $2.00 per task to evaluate "
                    "Model on the Intelligence Index.</p>"
                ),
            }

        def one_record():
            return {
                "present-but-absent": {
                    "id": "id-x",
                    "slug": "present-but-absent",
                    "model": "Present But Absent",
                    "release_date": "2026-01-20",
                    "indices": {"intelligence_index": 40.0},
                    "cost_per_task": None,
                    "median_performance": 100.0,
                    "prices": {},
                    "deprecated": False,
                }
            }

        known = {
            "present-but-absent": {
                "cost": 2.0,
                "fetched_at": 1_800_000_000.0,
                "deprecated": False,
            }
        }
        # A cost that was read a moment ago is used as it is.
        _costs, fetches = aa_pull._read_model_pages(
            one_record(),
            {},
            model_pages=model_page,
            offered=["present-but-absent"],
            known=known,
            now=1_800_000_100.0,
        )
        self.assertEqual(fetches, 0)
        self.assertEqual(calls, [])
        # A cost that is a week old is read again.
        _costs, fetches = aa_pull._read_model_pages(
            one_record(),
            {},
            model_pages=model_page,
            offered=["present-but-absent"],
            known=known,
            now=1_800_000_000.0 + 8 * 24 * 3600,
        )
        self.assertEqual(fetches, 1)
        self.assertEqual(len(calls), 1)

    def test_the_model_page_reads_are_capped(self):
        calls: list[str] = []

        def model_page(slug):
            calls.append(slug)
            return {
                "url": f"https://artificialanalysis.ai/models/{slug}",
                "http_status": 200,
                "bytes": 10,
                "blocked": False,
                "error": None,
                "text": "<p>no cost here</p>",
            }

        records = {
            f"model-{index}": {
                "id": f"id-{index}",
                "slug": f"model-{index}",
                "model": f"Model {index}",
                "release_date": "2026-01-20",
                "indices": {"intelligence_index": 40.0},
                "cost_per_task": None,
                "median_performance": 100.0,
                "prices": {},
                "deprecated": True,
            }
            for index in range(50)
        }
        _costs, fetches = aa_pull._read_model_pages(
            records,
            {},
            model_pages=model_page,
            offered=[f"model-{index}" for index in range(50)],
        )
        # The pull is capped, so a run never reads a hundred pages.
        self.assertEqual(fetches, aa_pull.MAX_MODEL_PAGE_FETCHES)
        self.assertEqual(len(calls), aa_pull.MAX_MODEL_PAGE_FETCHES)

    def test_a_deprecated_model_is_published_with_its_flag(self):
        # The model page of a deprecated model carries the model itself, and
        # the page says which model superseded it.
        text = page("grok/grok-4-5.html")
        if not text:
            self.skipTest("the model page fixture is not there")
        grok = aa_pull.parse_model_page(text)
        self.assertEqual(grok["slug"], "grok-4-5")
        self.assertTrue(grok["deprecated"])
        self.assertEqual(grok["deprecated_to"], "grok-4-6")
        self.assertAlmostEqual(grok["intelligence"], 38.8121153240657, places=6)
        record = aa_pull._record(
            "grok-4-5",
            grok["name"],
            creator=grok["creator"],
            intelligence=grok["intelligence"],
            estimated=grok["estimated"],
            cost_per_task=grok["cost_per_task"],
            cost_basis=aa_pull.COST_BASIS_PUBLISHED,
            release_date=grok["release_date"],
            reasoning=grok["reasoning"],
            deprecated=True,
        )
        self.assertTrue(record["deprecated"])
        # The model page publishes the cost per task in its own text, and
        # the published number is used as it is published.
        self.assertAlmostEqual(
            aa_pull._cost_in_text(text), 0.88, places=6
        )


def _page_for(url):
    """The page of a url, when the fixture has it."""
    if "leaderboards" in url:
        return page("models_leaderboards.html")
    if "aa-3d" in url:
        return page("aa3d.html")
    return page("models.html")


if __name__ == "__main__":
    unittest.main()
