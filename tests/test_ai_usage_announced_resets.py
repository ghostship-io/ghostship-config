"""Announcement evidence must change effective reset and pace without inventing usage."""
import sys
import unittest
from unittest.mock import patch
import tempfile
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"))
import announced_resets as announcements
import main
import model_selection
import reset_overrides
import snapshot
from metrics import SourceResult

URL = announcements.SOURCE + "/status/1234567890"
NOW = datetime.fromisoformat("2030-07-01T12:00:00+00:00").timestamp()


def post(text="All Codex limits reset tomorrow at 10am PT.", **kwargs):
    return {"url": URL, "text": text, "published_at": "2030-06-30T20:00:00Z", **kwargs}


class AnnouncedResetTests(unittest.TestCase):
    def test_announcement_never_postpones_an_earlier_provider_reset(self):
        results = [SourceResult("t3", "ok", windows=[
            {"provider": "codex", "quotaId": "session", "resetEpoch": NOW + 100},
            {"provider": "other", "quotaId": "weekly", "resetEpoch": NOW + 600000}])]
        self.assertEqual(announcements.overrides(results, {"announcements": [announcements.parse(post())]}, NOW), [])

    def test_crash_reservation_prevents_another_site_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "announcements.json"
            with patch.object(sys, "argv", ["announced-resets", "--output", str(path), "desktop"]), \
                    patch.object(announcements.time, "time", return_value=NOW), \
                    patch.object(announcements, "cli_call", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    announcements.main()
            document = json.loads(path.read_text())
            self.assertEqual(document["status"], "checking")
            self.assertEqual(document["checked_at"], NOW)
            with patch.object(announcements, "cli_call") as call:
                self.assertEqual(announcements.check(document, call, NOW + 1), document)
                call.assert_not_called()

    def test_explicit_announcement_flows_through_published_pacing(self):
        record = announcements.parse(post())
        self.assertEqual(record["reset_at"], "2030-07-01T17:00:00Z")
        measured = {"provider": "codex", "quotaId": "weekly", "kind": "weekly",
                    "usedRatio": .5, "resetEpoch": NOW + 600000,
                    "durationSeconds": 604800, "observedAtEpoch": NOW}
        results = [SourceResult("t3", "ok", windows=[measured.copy()])]
        before = model_selection.limiting_window([snapshot._window_record(measured, NOW)], "2030-07-01T12:00:00Z")
        reset_overrides.apply(results, announcements.overrides(results, {"announcements": [record]}, NOW), NOW)
        inputs = main.ranking_inputs(results, main.catalog_module.Catalog({}), {}, results[0].windows, now=NOW)
        window = snapshot._window_record(inputs["windows"]["codex"][0], NOW)
        limit = model_selection.limiting_window([window], "2030-07-01T12:00:00Z")
        self.assertEqual(limit["reset_label"], "announced reset")
        self.assertEqual(limit["reset_source"], "announced")
        self.assertEqual(limit["reset_at"], record["reset_at"])
        self.assertEqual(limit["provider_reset_at"], snapshot._iso(measured["resetEpoch"]))
        self.assertNotEqual(limit["pace_state"], before["pace_state"])
        self.assertEqual(limit["pace_state"], "ahead")
        self.assertEqual(results[0].windows[0]["usedRatio"], .5)
        self.assertEqual(results[0].windows[0]["observedAtEpoch"], NOW)
        gauges = snapshot.account_window_samples({"quota": {"accounts": {"codex": [window]}}})
        self.assertTrue(all("announced reset" in labels["label"] for _, labels, _ in gauges))
        published = main.build_snapshot(results, [], {"announced_resets": {"schema": 1,
            "status": "ok", "announcements": [record]}}, NOW, measured_windows=results[0].windows,
            catalog=main.catalog_module.Catalog({}))
        self.assertEqual(published["announced_resets"]["announcements"][0]["source_url"], URL)
        account_window = published["quota"]["accounts"]["codex"][0]
        self.assertEqual(account_window["reset_label"], "announced reset")
        self.assertEqual(account_window["reset_at"], record["reset_at"])
        self.assertEqual(announcements.overrides(results, {"announcements": [record]}, NOW + 18001), [])
        reset_overrides.apply(results, [{"provider": "codex", "quota_id": "weekly",
                                        "reset_at": "2030-07-01T18:00:00Z"}], NOW)
        self.assertEqual(results[0].windows[0]["resetSource"], "custom")
        self.assertEqual(results[0].windows[0]["providerResetEpoch"], measured["resetEpoch"])

    def test_ambiguous_banked_or_other_author_never_changes_capacity(self):
        for text in ("All Codex limits reset tomorrow before 10am PT.", "Reset day today!",
                     "All API limits reset tomorrow at 10am PT. Codex is unchanged.",
                     "All Codex users get a banked reset tomorrow at 10am PT.",
                     "All Codex limits reset tomorrow at 10am PST.",
                     "All Codex limits reset at 10am PT."):
            with self.subTest(text=text):
                record = announcements.parse(post(text))
                self.assertIsNone(record["reset_at"])
                self.assertEqual(record["confidence"], "low")
        self.assertIsNone(announcements.parse(post(url="https://example.org/status/123")))

    def test_blocked_check_stops_closes_and_retains_history(self):
        calls = []
        def call(op, **kw):
            calls.append((op, kw))
            if kw.get("action") == "open":
                return {"window_id": "lease"}
            if op == "browser.op":
                return {"extracts": {"announcements": {"blocked": True, "posts": [post()]}}}
            return {}
        document = {"schema": 1, "announcements": [announcements.parse(post())]}
        result = announcements.check(document, call, NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["announcements"], document["announcements"])
        self.assertEqual(calls[-1], ("browser.window", {"action": "close", "window_id": "lease"}))
        self.assertEqual(announcements.check(result, call, NOW + 100), result)
        self.assertEqual(len(calls), 4)
        self.assertEqual(result["sources"], [{"source_url": announcements.SOURCE, "status": "blocked"},
                                            {"source_url": announcements.RELAY, "status": "blocked"}])

    def test_personal_profile_is_explicit_in_desktop_calls(self):
        with patch.object(announcements.subprocess, "run") as run:
            run.return_value.stdout = json.dumps({"outcome": "success", "data": {"window_id": "lease"}})
            announcements.cli_call(["desktop"], "browser.window", action="open")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--identity") + 1], "personal")

    def test_readable_relay_keeps_primary_blocked_and_never_grants_capacity(self):
        calls = []
        def call(op, **kw):
            calls.append((op, kw))
            if kw.get("action") == "open":
                return {"window_id": "lease"}
            if op == "browser.op":
                primary = kw["steps"][0]["url"] == announcements.SOURCE
                return {"extracts": {"announcements": {"blocked": primary,
                                                        "posts": [] if primary else [post()]}}}
            return {}
        result = announcements.check({"schema": 1, "announcements": []}, call, NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"][0]["status"], "blocked")
        self.assertEqual(result["sources"][1]["status"], "ok")
        self.assertEqual(result["announcements"][0]["confidence"], "low")
        self.assertEqual(result["announcements"][0]["primary_source_url"], URL)
        self.assertTrue(result["announcements"][0]["source_url"].startswith(announcements.RELAY))
        self.assertEqual(announcements.overrides([], result, NOW), [])
        self.assertEqual(len(calls), 4)

    def test_unavailable_desktop_records_fixed_status(self):
        def call(*args, **kwargs):
            raise OSError("private transport failure")
        value = announcements.check({"schema": 1, "announcements": []}, call, NOW)
        self.assertEqual(value["status"], "unavailable")
        self.assertNotIn("private", str(value))

    def test_repeat_discovery_deduplicates_source(self):
        def call(op, **kw):
            if kw.get("action") == "open":
                return {"window_id": "lease"}
            if op == "browser.op":
                return {"extracts": {"announcements": {"blocked": False, "posts": [post(), post()]}}}
            return {}
        first = announcements.check({"schema": 1, "announcements": []}, call, NOW)
        second = announcements.check(first, call, NOW + announcements.INTERVAL)
        self.assertEqual(len(second["announcements"]), 1)
        self.assertEqual(second["status"], "ok")


if __name__ == "__main__":
    unittest.main()
