"""The Artificial Analysis public pull: the pages, the records and the diff.

The fixtures are the real pages the pull read, and the real snapshot it
built from them. The tests therefore reproduce the real naming differences
and the real cost per task of the published models.
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

import aa  # noqa: E402
import aa_diff  # noqa: E402
import aa_pull  # noqa: E402

NOW = 1_800_000_000.0
# The public pages, cut down to the smallest excerpt that still exercises
# the parser. They are committed with the tests: a test never reads a
# scratch path, and a missing fixture fails the test.
PAGES = Path(__file__).resolve().parent / "fixtures" / "ai-usage" / "aa-pages"
# The committed snapshots of the feed.
SNAPSHOTS = Path(__file__).resolve().parent / "fixtures" / "ai-usage"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def page(name):
    """One committed page excerpt."""
    path = PAGES / name
    if not path.exists():
        raise AssertionError(f"the page fixture {path} is missing")
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

    def test_a_fresh_cache_without_its_aa3d_file_still_pulls(self):
        """The 3D tier needs the AA-3D file; a fresh main cache must not skip it.

        On the host the main cache was fresh while the AA-3D file had never
        been written, so every run returned early and the 3D tier stayed empty.
        """
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
            fetched = []

            def read(url):
                fetched.append(url)
                return {"url": url, "http_status": 403, "bytes": 0,
                        "blocked": True, "error": "HTTP 403"}

            result = aa_pull.refresh(cache, now=NOW, read=read,
                                     aa3d_path=Path(folder) / "aa-3d.json")
            self.assertTrue(fetched)
            self.assertNotEqual(result.get("reason"), "the cache is still fresh")

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
        text = page("grok-4-5.html")
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


class FakeClock:
    """A clock the test moves by hand: no network, and no sleeping."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class PullBudgetTests(unittest.TestCase):
    """The AA-3D board is written first, and the model pages are bounded.

    The pull reads public pages over the network, and a model page is about
    four megabytes. The tests inject the reader and the clock, so a slow
    page is a number and not a minute of waiting.
    """

    # The models the committed leaderboard carries without a published cost.
    # Their own pages publish the cost, and the catalog offers them.
    DEPRECATED = (
        "claude-sonnet-4-5",
        "deepseek-v4-1",
        "gemini-3-pro",
        "grok-4-5",
        "llama-4-1",
        "qwen3-max",
    )

    def setUp(self):
        self.clock = FakeClock()
        # The pull measures its budget with this clock. A test moves it by
        # hand, so a slow page is a number and not a minute of waiting.
        self.previous_clock = getattr(aa_pull, "CLOCK", None)
        aa_pull.CLOCK = self.clock
        # The page reads, with the clock at the moment of the read.
        self.reads: list[tuple[str, float]] = []
        # The model page reads, with the clock at the moment of the read.
        self.model_reads: list[tuple[str, float]] = []
        # Whether the AA-3D board was on the disk when the first model page
        # was read.
        self.board_at_first_page: bool | None = None

    def tearDown(self):
        aa_pull.CLOCK = self.previous_clock

    def _reading(self, url, text, *, blocked=False):
        """One reading of a public page."""
        return {
            "url": url,
            "http_status": 403 if blocked else 200,
            "bytes": 0 if blocked else len(text),
            "blocked": blocked,
            "error": "HTTP 403" if blocked else None,
            "text": "" if blocked else text,
        }

    def _reader(self, *, read_seconds=5.0, aa3d_blocked=False):
        """The reader of the public pages. The clock moves with the read."""

        def read(url):
            self.reads.append((url, self.clock.now))
            self.clock.advance(read_seconds)
            if "aa-3d" in url:
                if aa3d_blocked:
                    return self._reading(url, "", blocked=True)
                return self._reading(url, page("aa3d.html"))
            if "leaderboards" in url:
                return self._reading(url, page("deprecated-leaderboard.html"))
            return self._reading(url, page("models.html"))

        return read

    def _model_pages(self, board_path, *, page_seconds=120.0):
        """The reader of the model pages, and the board that is already there."""

        def read(slug):
            self.model_reads.append((slug, self.clock.now))
            if self.board_at_first_page is None:
                self.board_at_first_page = board_path.exists()
            self.clock.advance(page_seconds)
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

        return read

    def _budget_started(self):
        """The moment the budget of the model pages started.

        The clock moves only while a page is read, and the AA-3D page is
        read first, so the budget starts at the second read.
        """
        self.assertGreaterEqual(len(self.reads), 2)
        return self.reads[1][1]

    def test_the_board_is_written_before_the_model_pages_are_read(self):
        # A model page that is slow must not lose the AA-3D board: the 3D
        # tier reads that file, and the pull is killed when it is slow.
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "aa.json"
            board = Path(folder) / "aa-3d.json"
            result = aa_pull.refresh(
                cache,
                now=NOW,
                read=self._reader(),
                model_pages=self._model_pages(board),
                aa3d_path=board,
                catalog_slugs=list(self.DEPRECATED),
            )
            # The board was on the disk while the first model page was read.
            self.assertTrue(self.board_at_first_page)
            self.assertTrue(board.exists())
            self.assertTrue(json.loads(board.read_text(encoding="utf-8"))["records"])
            # The model pages are read at 10, 130, 250 and 370 seconds of the
            # budget, and the fifth and the sixth are not read: the budget
            # has less than ninety seconds left.
            started = self._budget_started()
            self.assertEqual(
                [moment - started for _slug, moment in self.model_reads],
                [10, 130, 250, 370],
            )
            # The run ends at 490 seconds of the budget.
            self.assertEqual(self.clock.now - started, 490)
            self.assertEqual(len(self.model_reads), 4)
            self.assertEqual(result.get("model_page_fetches"), 4)
            self.assertEqual(result.get("model_page_skipped"), 2)
            # The quality cache is written even though two pages were not
            # read.
            self.assertEqual(result["status"], "ok")
            written = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(written.get("model_page_skipped"), 2)
            records = {entry["slug"]: entry for entry in written["records"]}
            # The models whose page was read carry the published cost.
            for slug in self.DEPRECATED[:4]:
                self.assertEqual(records[slug]["cost_per_task"], 1.0)
            # The models whose page was not read carry no cost at all: a
            # cost that was not read is unknown, never zero.
            for slug in self.DEPRECATED[4:]:
                self.assertIsNone(records[slug]["cost_per_task"])

    def test_a_failed_board_keeps_the_last_board_and_refreshes_the_cache(self):
        # The AA-3D page could not be read. The last good board is kept, and
        # the quality cache is refreshed: the board is not the quality data.
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "aa.json"
            board = Path(folder) / "aa-3d.json"
            last_good = (SNAPSHOTS / "aa-3d-measured.json").read_text(encoding="utf-8")
            board.write_text(last_good, encoding="utf-8")
            result = aa_pull.refresh(
                cache,
                now=NOW,
                read=self._reader(aa3d_blocked=True),
                model_pages=self._model_pages(board),
                aa3d_path=board,
                catalog_slugs=list(self.DEPRECATED),
            )
            # The last good board is neither written nor replaced.
            self.assertEqual(board.read_text(encoding="utf-8"), last_good)
            # The quality cache is refreshed anyway.
            self.assertEqual(result["status"], "ok")
            self.assertTrue(cache.exists())
            written = json.loads(cache.read_text(encoding="utf-8"))
            self.assertTrue(written["records"])


if __name__ == "__main__":
    unittest.main()
