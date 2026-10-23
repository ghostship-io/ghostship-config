"""Announcement evidence must change effective reset and pace without inventing usage."""
import sys
import re
import subprocess
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import asyncio
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
TOPIC = "https://community.openai.com/t/reset-announcement/12345"
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
                    patch.object(announcements, "desktop_check", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    announcements.main()
            document = json.loads(path.read_text())
            self.assertEqual(document["status"], "checking")
            self.assertEqual(document["checked_at"], NOW)
            with patch.object(announcements, "mcp_call") as call:
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

    def test_unrelated_features_and_other_authors_are_ignored(self):
        for text in ("Reset day today!", "I reset my computer today.",
                     "All Codex users get a banked reset tomorrow at 10am PT.",
                     "Codex usage limits reset weekly.", "Did Codex weekly limits reset today?",
                     "We are not resetting Codex usage limits today."):
            with self.subTest(text=text):
                self.assertIsNone(announcements.parse(post(text)))
        self.assertIsNone(announcements.parse(post(url="https://example.org/status/123")))
        for text in ("All Codex limits reset tomorrow before 10am PT.",
                     "All Codex limits reset tomorrow at 10am PST.",
                     "We are resetting Codex weekly usage limits later today."):
            with self.subTest(text=text):
                record = announcements.parse(post(text))
                self.assertIsNone(record["reset_at"])
                self.assertEqual(record["confidence"], "low")

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
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["sources"], [{"source_url": announcements.SOURCE, "status": "blocked"}])

    def test_personal_profile_is_explicit_in_desktop_calls(self):
        session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(
            structuredContent={"outcome": "success", "data": {"window_id": "lease"}})))
        value = asyncio.run(announcements.mcp_call(session, "browser.window", {"action": "open"}))
        self.assertEqual(value, {"window_id": "lease"})
        self.assertEqual(session.call_tool.call_args.args[0], "browser_window")
        self.assertEqual(session.call_tool.call_args.args[1]["identity"], "personal")

    def test_outer_runtime_success_does_not_hide_unavailable_desktop(self):
        session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(
            structuredContent={"outcome": "success", "data": {"outcome": "unavailable", "data": {}}})))
        with self.assertRaises(ValueError):
            asyncio.run(announcements.mcp_call(session, "browser.window", {"action": "open"}))

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


class EventConfirmationTests(unittest.TestCase):
    def document(self):
        entry = announcements.parse(post())
        entry.update(relay_source_url=TOPIC,
                     confidence='low', reason='community_relay', observed_at=NOW)
        return {'schema': 1, 'status': 'partial', 'checked_at': NOW, 'announcements': [entry]}

    def test_unverified_relay_is_published_with_link_before_confirmation_changes_pace(self):
        document = self.document()
        measured = {'provider': 'codex', 'quotaId': 'weekly', 'kind': 'weekly',
                    'usedRatio': .5, 'resetEpoch': NOW + 600000,
                    'durationSeconds': 604800, 'observedAtEpoch': NOW}
        results = [SourceResult('t3', 'ok', windows=[measured.copy()])]
        self.assertEqual(announcements.overrides(results, document, NOW), [])
        text = main.render([], [], NOW, 0, {'announced_resets': document})
        self.assertIn('label="announced (unverified)"', text)
        self.assertIn(document['announcements'][0]['source_url'], text)
        self.assertIn('ghostship_ai_announced_reset_info', text)
        dashboard = json.loads((Path(__file__).resolve().parents[1] /
            'modules/self-hosted/siem/dashboards/ai-usage.json').read_text())
        panel = next(item for item in dashboard['panels'] if item['id'] == 202)
        self.assertIn('ghostship_ai_announced_reset_info', panel['targets'][0]['expr'])
        self.assertTrue(panel['options']['enablePagination'])
        link = panel['fieldConfig']['overrides'][0]['properties'][0]['value'][0]
        self.assertEqual(link['url'], '${__value.raw}')
        before = model_selection.limiting_window([snapshot._window_record(measured, NOW)], '2030-07-01T12:00:00Z')
        announcements.confirm(document, document['announcements'][0]['source_url'], '2030-07-01T17:00:00Z', NOW)
        reset_overrides.apply(results, announcements.overrides(results, document, NOW), NOW)
        published = main.build_snapshot(results, [], {'announced_resets': document}, NOW,
            measured_windows=results[0].windows, catalog=main.catalog_module.Catalog({}))
        window = published['quota']['accounts']['codex'][0]
        self.assertEqual(window['reset_at'], '2030-07-01T17:00:00Z')
        self.assertEqual(window['reset_label'], 'announced reset')
        after = model_selection.limiting_window([window], '2030-07-01T12:00:00Z')
        self.assertNotEqual(after['pace_state'], before['pace_state'])
        self.assertEqual(after['pace_state'], 'ahead')
        self.assertEqual(results[0].windows[0]['usedRatio'], .5)
        self.assertEqual(announcements.overrides(results, document, NOW + 18001), [])

    def test_confirmation_is_explicit_bounded_and_requires_a_recorded_source(self):
        for reset in ('2030-07-01T17:00:00', '2030-06-30T17:00:00Z', '2030-08-01T17:00:00Z', 'unknown'):
            with self.subTest(reset=reset), self.assertRaises(ValueError):
                announcements.confirm(self.document(), URL, reset, NOW)
        with self.assertRaises(ValueError):
            announcements.confirm(self.document(), TOPIC + '#announcement-999', '2030-07-01T17:00:00Z', NOW)

    def test_confirmation_cli_writes_the_shared_cache_without_browsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'announcements.json'
            document = self.document()
            path.write_text(json.dumps(document))
            argv = ['announced-resets', '--output', str(path), '--confirm',
                    document['announcements'][0]['source_url'], '--reset-at', '2030-07-01T17:00:00Z']
            with patch.object(sys, 'argv', argv), patch.object(announcements.os, 'geteuid', return_value=0), \
                 patch.object(announcements.time, 'time', return_value=NOW), \
                 patch.object(announcements, 'desktop_check') as desktop:
                announcements.main()
                desktop.assert_not_called()
            self.assertEqual(json.loads(path.read_text())['announcements'][0]['confidence'], 'confirmed')
            with patch.object(sys, 'argv', argv), patch.object(announcements.os, 'geteuid', return_value=1000), \
                 self.assertRaises(SystemExit):
                announcements.main()

    def test_notice_retries_failure_and_is_not_repeated_after_success(self):
        document = self.document()
        with patch.object(announcements.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as publish:
            announcements.notify_pending(document, 'fixture-notify', NOW)
            self.assertNotIn('notice_sent_at', document['announcements'][0])
            self.assertIn(document['announcements'][0]['source_url'], publish.call_args.args[0][-1])
        with patch.object(announcements.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as publish:
            announcements.notify_pending(document, 'fixture-notify', NOW + 1)
            announcements.notify_pending(document, 'fixture-notify', NOW + 2)
            self.assertEqual(publish.call_count, 1)
        self.assertEqual(announcements.overrides([], document, NOW), [])

    def test_rediscovery_preserves_confirmation_and_successful_notice(self):
        document = self.document()
        url = document['announcements'][0]['source_url']
        announcements.confirm(document, url, '2030-07-01T18:00:00Z', NOW)
        document['announcements'][0]['notice_sent_at'] = NOW
        def call(op, **kwargs):
            if kwargs.get('action') == 'open':
                return {'window_id': 'lease'}
            if op == 'browser.op':
                current = kwargs['steps'][0]['url']
                return {'extracts': {'announcements': {'blocked': False,
                    'posts': [post()]}}}
            return {}
        result = announcements.check(document, call, NOW + announcements.INTERVAL)
        self.assertEqual(result['announcements'][0]['confidence'], 'confirmed')
        self.assertEqual(result['announcements'][0]['notice_sent_at'], NOW)

        self.assertEqual(result['announcements'][0]['reset_at'], '2030-07-01T18:00:00Z')
        self.assertEqual(result['announcements'][0]['reason'], 'operator_confirmed')


class HourlyPrimaryTests(unittest.TestCase):
    def browser(self, visited, blocked=False):
        def call(op, **kwargs):
            if kwargs.get('action') == 'open':
                return {'window_id': 'lease'}
            if op == 'browser.op':
                url = kwargs['steps'][0]['url']
                visited.append(url)
                return {'extracts': {'announcements': {
                    'blocked': blocked, 'posts': [post()], 'topics': []}}}
            return {}
        return call

    def test_hourly_primary_and_eight_hour_wall_backoff(self):
        visited = []
        initial = {'schema': 1, 'announcements': []}
        first = announcements.check(initial, self.browser(visited), NOW)
        self.assertEqual(first['next_check_at'], NOW + 3600)
        announcements.check(first, self.browser(visited), NOW + 3599)
        self.assertEqual(visited, [announcements.SOURCE])
        blocked = announcements.check(first, self.browser(visited, True), NOW + 3600)
        self.assertEqual(blocked['next_check_at'], NOW + 9 * 3600)
        count = len(visited)
        announcements.check(blocked, self.browser(visited), NOW + 8 * 3600)
        self.assertEqual(len(visited), count)
        recovered = announcements.check(blocked, self.browser(visited), NOW + 9 * 3600)
        self.assertEqual(recovered['next_check_at'], NOW + 10 * 3600)
        self.assertEqual(recovered['sources'][0]['status'], 'ok')
        self.assertNotIn('blocked_since', recovered)

    def test_blocked_notice_once_per_episode_with_failed_publication_retry(self):
        document = announcements.check({'schema': 1, 'announcements': []}, self.browser([], True), NOW)
        with patch.object(announcements.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            announcements.notify_pending(document, 'fixture-notify', NOW)
        self.assertNotIn('blocked_notice_sent_at', document)
        with patch.object(announcements.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as publish:
            announcements.notify_pending(document, 'fixture-notify', NOW + 1)
            announcements.notify_pending(document, 'fixture-notify', NOW + 2)
            still_blocked = announcements.check(document, self.browser([], True), NOW + 8 * 3600)
            announcements.notify_pending(still_blocked, 'fixture-notify', NOW + 8 * 3600)
            self.assertEqual(publish.call_count, 1)
            first_key = publish.call_args.args[0]
            recovered = announcements.check(still_blocked, self.browser([]), NOW + 16 * 3600)
            # Ignore the reset post: this test concerns wall notices only.
            recovered['announcements'] = []
            blocked_again = announcements.check(recovered, self.browser([], True), NOW + 17 * 3600)
            announcements.notify_pending(blocked_again, 'fixture-notify', NOW + 17 * 3600)
            self.assertEqual(publish.call_count, 2)
            self.assertNotEqual(first_key[first_key.index('--dedupe') + 1],
                                publish.call_args.args[0][first_key.index('--dedupe') + 1])

    def test_existing_relay_receipt_suppresses_primary_post_notice_in_either_order(self):
        for reverse in (False, True):
            relay = EventConfirmationTests().document()['announcements'][0]
            relay.update(source_url=TOPIC + '#announcement-1234567890', primary_source_url=URL, notice_sent_at=NOW)
            primary = announcements.parse(post())
            records = [relay, primary]
            if reverse:
                records.reverse()
            with patch.object(announcements.subprocess, 'run') as publish:
                announcements.notify_pending({'announcements': records}, 'fixture-notify', NOW + 1)
                publish.assert_not_called()
            self.assertEqual(primary['notice_sent_at'], NOW)

    def test_new_posts_share_canonical_notice_key_and_all_confidences_notify(self):
        relay = EventConfirmationTests().document()['announcements'][0]
        primary = announcements.parse(post())
        low = announcements.parse(post('We are resetting Codex weekly usage limits later today.', url=URL + '1'))
        document = {'announcements': [relay, primary, low]}
        with patch.object(announcements.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as publish:
            announcements.notify_pending(document, 'fixture-notify', NOW)
            announcements.notify_pending(document, 'fixture-notify', NOW + 1)
            self.assertEqual(publish.call_count, 2)
            self.assertTrue(any('Codex reset announced' in call.args[0] for call in publish.call_args_list))
            self.assertTrue(any('Codex reset announcement needs confirmation' in call.args[0]
                                for call in publish.call_args_list))
        self.assertTrue(all(row['notice_sent_at'] == NOW for row in document['announcements']))

    def test_crash_reservation_backs_off_for_eight_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'announcements.json'
            with patch.object(sys, 'argv', ['checker', '--output', str(path), 'desktop']), \
                 patch.object(announcements.time, 'time', return_value=NOW), \
                 patch.object(announcements, 'desktop_check', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    announcements.main()
            document = json.loads(path.read_text())
            self.assertFalse(announcements.due(document, NOW + 7 * 3600))
            self.assertTrue(announcements.due(document, NOW + 8 * 3600))

    def test_timer_invokes_hourly_but_cache_owns_wall_backoff(self):
        source = (Path(__file__).resolve().parents[1] /
                  'modules/self-hosted/ai-usage/announced-resets.nix').read_text()
        self.assertIn('OnUnitActiveSec = "1h";', source)


class UsageLimitEventTests(unittest.TestCase):
    def weekly(self, **kwargs):
        return {'provider': 'codex', 'quotaId': 'weekly', 'kind': 'weekly', 'usedRatio': 1.0,
                'durationSeconds': 604800, 'resetEpoch': NOW + 500000,
                'observedAtEpoch': NOW - 100, **kwargs}

    def test_explicit_weekly_reset_has_quote_post_time_scope_and_confirmation(self):
        record = announcements.parse(post('We are resetting all Codex weekly usage limits tomorrow at 10am PT.'))
        self.assertEqual(record['confidence'], 'confirmed')
        self.assertEqual(record['published_at'], '2030-06-30T20:00:00Z')
        self.assertIn('resetting all Codex weekly', record['quote'])
        self.assertEqual(record['products'], ['codex'])
        self.assertEqual(record['plans'], ['all'])
        self.assertEqual(record['windows'], ['weekly'])
        self.assertEqual(record['reset_at'], '2030-07-01T17:00:00Z')

    def test_explicit_iso_and_24_hour_reset_clocks_are_confirmed(self):
        for text in ('All Codex weekly usage limits reset at 2030-07-01T17:00:00Z.',
                     'All Codex weekly usage limits reset tomorrow at 10:00 PT.'):
            with self.subTest(text=text):
                record = announcements.parse(post(text))
                self.assertEqual(record['confidence'], 'confirmed')
                self.assertEqual(record['reset_at'], '2030-07-01T17:00:00Z')

    def test_unrelated_mentions_are_not_events_but_ambiguous_announcements_are(self):
        for text in ('I reset my laptop today.', 'Codex reset day!',
                     'The Codex usage limits reset weekly.',
                     'Here is how to reset the Codex usage display today.',
                     'We reset the Codex usage dashboard today.'):
            self.assertIsNone(announcements.parse(post(text)), text)
        record = announcements.parse(post('We are resetting Codex weekly usage limits later today.'))
        self.assertEqual(record['confidence'], 'low')
        self.assertEqual(record['windows'], ['weekly'])
        self.assertIsNone(record['reset_at'])
        self.assertEqual(announcements.overrides([SourceResult('fixture', 'ok', windows=[self.weekly()])],
                                               {'announcements': [record]}, NOW), [])

    def test_known_time_with_unspecified_window_stays_unverified(self):
        record = announcements.parse(post('We are resetting Codex usage limits now.'))
        self.assertEqual(record['windows'], ['unknown'])
        self.assertEqual(record['reset_at'], record['published_at'])
        self.assertEqual(record['confidence'], 'low')
        with self.assertRaises(ValueError):
            announcements.confirm({'announcements': [record]}, URL, '2030-07-01T17:00:00Z', NOW)

    def test_weekly_event_does_not_override_session_chatgpt_or_unknown_plan(self):
        record = announcements.parse(post('We are resetting Codex Pro weekly usage limits tomorrow at 10am PT.'))
        windows = [self.weekly(plan='pro'), self.weekly(quotaId='session', kind='session', plan='pro'),
                   self.weekly(provider='chatgpt', plan='pro'), self.weekly()]
        overrides = announcements.overrides([SourceResult('fixture', 'ok', windows=windows)],
                                            {'announcements': [record]}, NOW)
        self.assertEqual(len(overrides), 1)
        self.assertEqual(overrides[0]['quota_id'], 'weekly')
        self.assertEqual(overrides[0]['provider'], 'codex')

    def test_scope_ignores_other_launch_prose_and_plus_as_a_conjunction(self):
        record = announcements.parse(post('ChatGPT Plus is getting a feature. '
            'Plus, we are resetting all Codex weekly usage limits now.'))
        self.assertEqual(record['products'], ['codex'])
        self.assertEqual(record['plans'], ['all'])
        self.assertEqual(record['windows'], ['weekly'])
        self.assertEqual(record['confidence'], 'confirmed')
        self.assertNotIn('getting a feature', record['quote'])

    def test_explicit_five_hour_and_chatgpt_scope_are_separate(self):
        record = announcements.parse(post('All ChatGPT Plus 5h usage limits reset tomorrow at 10am PT.'))
        self.assertEqual(record['confidence'], 'confirmed')
        self.assertEqual(record['products'], ['chatgpt'])
        self.assertEqual(record['windows'], ['session'])
        self.assertEqual(record['plans'], ['plus'])
        self.assertFalse(announcements.reset_events.matches(record, self.weekly(plan='plus')))

    def test_completed_weekly_reset_changes_published_pace_and_picker_headroom(self):
        published_at = '2030-07-01T11:59:40Z'
        record = announcements.parse(post('We just reset all Codex weekly usage limits now.', published_at=published_at))
        weekly = self.weekly()
        session = self.weekly(quotaId='session', kind='session', usedRatio=.2, observedAtEpoch=NOW)
        results = [SourceResult('fixture', 'ok', windows=[weekly, session])]
        before = snapshot._window_record(weekly.copy(), NOW)
        announcements.reset_events.apply_completed(results, {'announcements': [record]}, NOW)
        self.assertEqual(weekly['usedRatio'], 0)
        self.assertEqual(weekly['providerUsedRatio'], 1)
        self.assertEqual(session['usedRatio'], .2)
        self.assertEqual(weekly['resetEpoch'], NOW - 20 + 604800)
        self.assertEqual(weekly['observedAtEpoch'], NOW - 20)
        inputs = main.ranking_inputs(results, main.catalog_module.Catalog({}), {}, results[0].windows, now=NOW)
        window = inputs['windows']['codex'][0]
        self.assertEqual(main.ranking_module._window_state(window, NOW), ('known', 1.0))
        failure = {'scope': 'account', 'reason': 'account_usage_limit', 'observed_at': NOW - 50}
        self.assertTrue(main.ranking_module._quota_recovered(failure, inputs['windows']['codex'], NOW))
        published = main.build_snapshot(results, [], {'announced_resets': {'announcements': [record]}}, NOW,
                                       measured_windows=results[0].windows, catalog=main.catalog_module.Catalog({}))
        actual = published['quota']['accounts']['codex'][0]
        self.assertEqual(published['quota']['provider_capacity']['codex']['remaining_ratio'], .8)
        self.assertEqual(published['quota']['provider_capacity']['codex']['unknown_windows'], 0)
        self.assertEqual(actual['remaining_ratio'], 1)
        self.assertEqual(actual['evidence'], 'announced_reset')
        self.assertEqual(actual['provider_used_ratio'], 1)
        self.assertEqual(actual['announcement_url'], URL)
        self.assertEqual(actual['reset_source'], 'announced')
        gauges = snapshot.account_window_samples(published)
        self.assertTrue(any(name == 'ghostship_ai_account_window_remaining_ratio' and value == 1
                            and labels['evidence'] == 'announced_reset' for name, labels, value in gauges))
        self.assertNotEqual(model_selection.limiting_window([actual], '2030-07-01T12:00:00Z')['pace_state'],
                            model_selection.limiting_window([before], '2030-07-01T12:00:00Z')['pace_state'])
        # Reapplication is idempotent and does not erase provider provenance.
        announcements.reset_events.apply_completed(results, {'announcements': [record]}, NOW + 1)
        self.assertEqual(weekly['providerUsedRatio'], 1)

    def test_newer_provider_truth_custom_override_and_expired_event_win(self):
        record = announcements.parse(post('We just reset all Codex weekly usage limits now.',
                                          published_at='2030-07-01T11:59:40Z'))
        for window, now in ((self.weekly(observedAtEpoch=NOW, usedRatio=.3), NOW),
                            (self.weekly(resetSource='custom'), NOW),
                            (self.weekly(), NOW + 604800)):
            original = dict(window)
            announcements.reset_events.apply_completed([SourceResult('fixture', 'ok', windows=[window])],
                                                      {'announcements': [record]}, now)
            self.assertEqual(window, original)
        weekly = self.weekly()
        announcements.reset_events.apply_completed([SourceResult('fixture', 'ok', windows=[weekly])],
                                                  {'announcements': [record]}, NOW + 1801)
        inputs = main.ranking_inputs([], main.catalog_module.Catalog({}), {}, [weekly], now=NOW + 1801)
        self.assertEqual(main.ranking_module._window_state(inputs['windows']['codex'][0], NOW + 1801),
                         ('unknown', None))

    def test_migration_drops_keyword_records_but_preserves_receipts_and_recheck_urls(self):
        legacy = {'source_url': TOPIC + '#announcement-1234567890', 'primary_source_url': URL,
                  'confidence': 'low', 'scope': 'unknown', 'notice_sent_at': NOW}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.json'
            path.write_text(json.dumps({'schema': 1, 'announcements': [legacy, {'source_url': URL}]}))
            document = announcements.load(path)
        self.assertEqual(document['announcements'], [])
        self.assertEqual(document['recheck_urls'], [URL])
        self.assertEqual(document['notice_receipts'], {URL: NOW})
        self.assertEqual(list(announcements.samples(document)), [])
        document['announcements'] = [announcements.parse(post())]
        with patch.object(announcements.subprocess, 'run') as publish:
            announcements.notify_pending(document, 'fixture-notify', NOW + 1)
            publish.assert_not_called()

    def test_notice_receipts_outlive_the_event_history_bound(self):
        receipts = {URL + str(i): NOW for i in range(250)}
        receipts[URL] = NOW
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.json'
            path.write_text(json.dumps({'schema': 1, 'announcements': [], 'notice_receipts': receipts}))
            document = announcements.load(path)
        document['announcements'] = [announcements.parse(post())]
        with patch.object(announcements.subprocess, 'run') as publish:
            announcements.notify_pending(document, 'fixture-notify', NOW + 1)
            publish.assert_not_called()
        self.assertEqual(len(document['notice_receipts']), 251)

    def test_migration_rechecks_primary_posts_and_ignores_non_announcements(self):
        visited = []
        def call(op, **kwargs):
            if kwargs.get('action') == 'open':
                return {'window_id': 'lease'}
            if op == 'browser.op':
                url = kwargs['steps'][0]['url']; visited.append(url)
                posts = [post('I reset my laptop today.')] if url == URL else [post()]
                return {'extracts': {'announcements': {'blocked': False, 'posts': posts}}}
            return {}
        document = announcements.check({'schema': 1, 'announcements': [], 'recheck_urls': [URL]}, call, NOW)
        self.assertEqual(visited, [announcements.SOURCE, URL])
        self.assertEqual(document['recheck_urls'], [])
        # Timeline evidence remains valid, but the permalink correction removes it.
        self.assertEqual(document['announcements'], [])

    def test_provider_series_contains_bounded_quote_scope_time_and_primary_link(self):
        record = announcements.parse(post())
        rows = list(announcements.samples({'announcements': [record]}))
        self.assertEqual(len(rows), 1)
        name, labels, value = rows[0]
        self.assertEqual(name, 'ghostship_ai_announced_reset_info')
        self.assertEqual(labels['provider'], 'codex')
        self.assertEqual(labels['source_url'], URL)
        self.assertEqual(labels['published_at'], record['published_at'])
        self.assertEqual(labels['quote'], record['quote'])
        self.assertEqual(labels['windows'], 'all')
        self.assertEqual(labels['reset_at'], record['reset_at'])
        self.assertEqual(labels['confidence'], 'confirmed')
        self.assertEqual(value, 1)

    def test_deployed_checker_keeps_its_parser_module_on_python_import_path(self):
        source = (Path(__file__).resolve().parents[1] /
                  'modules/self-hosted/ai-usage/announced-resets.nix').read_text()
        self.assertEqual(source.count('${./collector}/announced_resets.py'), 2)


class SandboxedDesktopTransportTests(unittest.TestCase):
    def test_deployed_wrapper_uses_the_remote_api_instead_of_local_storage(self):
        source = (Path(__file__).resolve().parents[1] /
                  'modules/self-hosted/ai-usage/announced-resets.nix').read_text()
        script = re.search(r'desktop = pkgs.writeShellScript "[^"]+" \'\'(.*?)\'\';', source, re.S)[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bin').mkdir()
            podman = root / 'bin/podman'
            podman.write_text('#!/bin/sh\n[ "$1" = "--remote" ] || exit 42\n[ "$2" = "exec" ] || exit 43\ncat\n')
            podman.chmod(0o700)
            result = subprocess.run(['bash', '-c', script.replace('${pkgs.podman}', str(root))],
                                    input='MCP probe\n', text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'MCP probe\n')


if __name__ == "__main__":
    unittest.main()
