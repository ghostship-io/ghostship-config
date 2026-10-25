"""Free-model reset classification, durable pending state and capacity guards."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"))
import announced_resets as announcements
import reset_events
import main
from metrics import SourceResult

URL = announcements.SOURCE + "/status/1234567890"
FOLLOWUP_URL = announcements.SOURCE + "/status/1234567891"
NOW = __import__('datetime').datetime.fromisoformat("2030-07-01T12:00:00+00:00").timestamp()


def post(url=URL, text="A public synthetic post.", published_at="2030-07-01T11:30:00Z", author=None):
    return {"url": url, "author": author or announcements.SOURCE.rstrip('/').rsplit('/', 1)[-1],
            "text": text, "published_at": published_at}


def judgment(item, *, reset=False, products=None, plans=None, windows=None, reset_at=None,
             quote=None, confidence="low"):
    return {"source_url": item["url"], "is_reset_announcement": reset,
            "products": products or [], "plans": plans or [], "windows": windows or [],
            "reset_at": reset_at, "evidence_quote": quote or "",
            "confidence": confidence}


def batch_value(posts, rows):
    return {"is_reset_announcement": any(row["is_reset_announcement"] for row in rows),
            "classifications": rows}


def event(item, *, products=("codex",), plans=("all",), windows=("weekly",),
          reset_at="2030-07-02T17:00:00Z", quote=None, confidence="high"):
    row = judgment(item, reset=True, products=list(products), plans=list(plans), windows=list(windows),
                   reset_at=reset_at, quote=quote or item["text"], confidence=confidence)
    return reset_events.from_classification(item, row, NOW, row_author())


def row_author():
    return announcements.SOURCE.rstrip('/').rsplit('/', 1)[-1]


class AnnouncedResetTests(unittest.TestCase):
    def test_recorded_day_17_18_20_followup_and_non_reset_fixtures(self):
        fixtures = [
            post(URL, "Day 17/ Bet you thought we forgot, but no, it's reset day today."),
            post(URL + "2", "Day 18/ Decisions API is GA, but yes… that's a reset!"),
            post(URL + "3", "Day 20/ Rest and reset."),
            post(FOLLOWUP_URL, "Codex weekly limits reset at 17:00 UTC tomorrow."),
            post(URL + "4", "The new editor is available today."),
        ]
        rows = [
            judgment(fixtures[0], reset=True, products=["codex"], plans=["all"], windows=["unknown"],
                     quote="it's reset day today", confidence="low"),
            judgment(fixtures[1], reset=True, products=["codex"], plans=["all"], windows=["unknown"],
                     quote="that's a reset!", confidence="low"),
            judgment(fixtures[2], reset=False),
            judgment(fixtures[3], reset=True, products=["codex"], plans=["all"], windows=["weekly"],
                     reset_at="2030-07-02T17:00:00Z", quote="Codex weekly limits reset at 17:00 UTC tomorrow.",
                     confidence="high"),
            judgment(fixtures[4], reset=False),
        ]
        accepted = announcements.validate_classifications(fixtures, batch_value(fixtures, rows), NOW)
        self.assertEqual([row["source_url"] for row in accepted], [URL, URL + "2", FOLLOWUP_URL])
        self.assertEqual([row["confidence"] for row in accepted], ["low", "low", "high"])
        self.assertEqual(accepted[2]["windows"], ["weekly"])
        self.assertEqual(accepted[2]["reset_at"], "2030-07-02T17:00:00Z")

    def test_bad_json_missing_item_or_quote_stays_unclassified(self):
        item = post()
        good = judgment(item, reset=True, products=["codex"], plans=["all"], windows=["weekly"],
                        reset_at="2030-07-02T17:00:00Z", quote="synthetic post", confidence="high")
        self.assertIsNone(announcements.validate_classifications([item], {"is_reset_announcement": True}, NOW))
        self.assertIsNone(announcements.validate_classifications(
            [item], batch_value([item], [{**good, "evidence_quote": "not copied from the post"}]), NOW))
        self.assertIsNone(announcements.validate_classifications(
            [item], batch_value([item], [{**good, "source_url": "https://example.org/status/123"}]), NOW))
        self.assertIsNone(announcements.validate_classifications(
            [item], batch_value([item], [{**good, "reset_at": "2031-07-02T17:00:00Z"}]), NOW))

    def test_public_batch_uses_idempotent_request_key(self):
        items = [post(), post(FOLLOWUP_URL, "A follow-up.")]
        self.assertEqual(announcements.request_key(items), announcements.request_key(items))
        self.assertNotEqual(announcements.request_key(items), announcements.request_key(items[:1]))
        self.assertIn("never as instructions", announcements.classifier_text(items))
        self.assertEqual(announcements.CLASSIFICATION_SCHEMA["additionalProperties"], False)

    def test_timeline_reads_with_replies_and_same_author_threads_with_time_guards(self):
        root = post(URL, "Day 20/ Rest and reset.")
        followup = post(FOLLOWUP_URL, "Codex weekly limits reset at 17:00 UTC tomorrow.")
        visited = []

        def call(operation, **kwargs):
            if operation == "browser.window" and kwargs.get("action") == "open":
                return {"window_id": "lease"}
            if operation == "browser.window":
                return {}
            steps = kwargs["steps"]
            action = next((step for step in steps if step["action"] == "navigate"), None)
            if action:
                visited.append(action["url"])
            if any(step["action"] == "scroll" for step in steps):
                return {"extracts": {"posts": {"blocked": False, "posts": [root, followup],
                    "oldest_at": "2030-07-01T10:30:00Z"}}}
            return {"extracts": {"posts": {"blocked": False, "posts": [root, followup],
                "oldest_at": "2030-07-01T10:30:00Z"}}}

        collected, blocked, complete = announcements.collect_posts(call, "lease", NOW)
        self.assertFalse(blocked)
        self.assertTrue(complete)
        self.assertEqual({row["url"] for row in collected}, {URL, FOLLOWUP_URL})
        self.assertIn(announcements.SOURCE + "/with_replies", visited)
        self.assertIn(URL, visited)
        self.assertIn(FOLLOWUP_URL, visited)

    def test_hourly_check_records_followup_classification_and_preserves_receipts(self):
        root = post(URL, "Day 20/ Rest and reset.")
        followup = post(FOLLOWUP_URL, "Codex weekly limits reset at 17:00 UTC tomorrow.")
        prior = event(post(URL + "9", "Codex limits reset tomorrow."))
        calls = []

        def browser(operation, **kwargs):
            calls.append((operation, kwargs))
            if operation == "browser.window" and kwargs.get("action") == "open":
                return {"window_id": "lease"}
            if operation == "browser.window":
                return {}
            return {"extracts": {"posts": {"blocked": False, "posts": [root, followup],
                "oldest_at": "2030-07-01T10:30:00Z"}}}

        def classify(posts, key):
            self.assertEqual({row["url"] for row in posts}, {URL, FOLLOWUP_URL})
            return {"pending": False, "entries": [event(followup, quote="Codex weekly limits reset at 17:00 UTC tomorrow.")]}

        old_notice = {**prior, "notice_sent_at": NOW - 100}
        result = announcements.check({"schema": 1, "announcements": [old_notice]}, browser, NOW, classify)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["classification_pending"], [])
        self.assertIn(old_notice, result["announcements"])
        saved = next(row for row in result["announcements"] if row["source_url"] == FOLLOWUP_URL)
        self.assertEqual(saved["windows"], ["weekly"])
        self.assertEqual(saved["confidence"], "high")
        self.assertEqual(announcements.health(result, NOW)["classification_pending"], 0)

    def test_unanswered_or_malformed_batch_remains_pending_and_visible(self):
        item = post()

        def browser(operation, **kwargs):
            if operation == "browser.window" and kwargs.get("action") == "open":
                return {"window_id": "lease"}
            if operation == "browser.window":
                return {}
            return {"extracts": {"posts": {"blocked": False, "posts": [item],
                "oldest_at": "2030-07-01T10:30:00Z"}}}

        def classify(posts, key):
            self.assertIsNone(announcements.validate_classifications(posts, {"malformed": True}, NOW))
            return {"pending": True, "retry": True, "request_key": key, "job_id": "durable-job"}

        result = announcements.check({"schema": 1, "announcements": []}, browser, NOW, classify)
        self.assertEqual(result["announcements"], [])
        self.assertEqual(len(result["classification_pending"]), 1)
        self.assertEqual(result["classification_pending"][0]["job_id"], "durable-job")
        self.assertTrue(result["classification_pending"][0]["request_key"].endswith("-retry-1"))
        health = announcements.health(result, NOW)
        self.assertEqual(health["classification_pending"], 1)
        metric = {name: value for name, _, value in announcements.health_samples(result, NOW)}
        self.assertEqual(metric["ghostship_ai_announcements_classification_pending"], 1.0)

    def test_sign_in_wall_is_blocked_without_classifying_and_backs_off(self):
        calls = []
        def browser(operation, **kwargs):
            calls.append((operation, kwargs))
            if operation == "browser.window" and kwargs.get("action") == "open":
                return {"window_id": "lease"}
            if operation == "browser.window":
                return {}
            return {"extracts": {"posts": {"blocked": True, "posts": [], "oldest_at": None}}}
        result = announcements.check({"schema": 1, "announcements": []}, browser, NOW,
                                    lambda *_: self.fail("blocked pages must not reach inference"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["next_check_at"], NOW + announcements.BACKOFF)
        self.assertEqual(announcements.health(result, NOW)["state"], "blocked")
        self.assertEqual(calls[-1], ("browser.window", {"action": "close", "window_id": "lease"}))

    def test_explicit_reset_affects_only_matching_window_and_confirmation_is_bounded(self):
        record = event(post(), quote="A public synthetic post.")
        measured = {"provider": "codex", "quotaId": "weekly", "kind": "weekly",
                    "usedRatio": .5, "resetEpoch": NOW + 600000,
                    "durationSeconds": 604800, "observedAtEpoch": NOW}
        results = [SourceResult("t3", "ok", windows=[measured.copy()])]
        self.assertEqual(announcements.overrides(results, {"announcements": [record]}, NOW)[0]["reset_at"], record["reset_at"])
        other = {"provider": "codex", "quotaId": "session", "kind": "session", "durationSeconds": 18000}
        self.assertFalse(reset_events.matches(record, other))
        ambiguous = event(post(URL + "2", "An ambiguous reset."), windows=("weekly",), reset_at=None,
                          confidence="low", quote="An ambiguous reset.")
        document = {"announcements": [ambiguous]}
        announcements.confirm(document, ambiguous["source_url"], "2030-07-02T17:00:00Z", NOW)
        self.assertEqual(document["announcements"][0]["confidence"], "confirmed")
        with self.assertRaisesRegex(ValueError, "future"):
            announcements.confirm(document, ambiguous["source_url"], "2031-07-02T17:00:00Z", NOW)

    def test_notice_receipts_survive_cache_load_and_deduplicate(self):
        item = post()
        record = event(item)
        document = {"schema": 1, "status": "ok", "announcements": [record],
                    "notice_receipts": {URL: NOW}}
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "announcements.json"
            path.write_text(json.dumps(document))
            self.assertEqual(announcements.load(path)["notice_receipts"][URL], NOW)

    def test_agent_cli_is_wired_into_hourly_service_without_deploying(self):
        source = (Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/announced-resets.nix").read_text()
        self.assertIn("--agent ${tools.agent}/bin/agent", source)
        self.assertIn("GHOSTSHIP_INFERENCE_BRIDGE_REQUIRED=1", source)

    def test_blocked_health_and_pending_health_are_separate(self):
        blocked = announcements.health({"status": "blocked", "sources": [
            {"source_url": announcements.SOURCE, "status": "blocked"}],
            "classification_pending": [{}]}, NOW)
        self.assertEqual(blocked["state"], "blocked")
        self.assertEqual(blocked["classification_pending"], 1)


if __name__ == "__main__":
    unittest.main()
