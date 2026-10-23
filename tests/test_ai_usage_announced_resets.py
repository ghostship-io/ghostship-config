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

    def test_readable_relay_keeps_primary_blocked_and_never_grants_capacity(self):
        calls = []
        def call(op, **kw):
            calls.append((op, kw))
            if kw.get("action") == "open":
                return {"window_id": "lease"}
            if op == "browser.op":
                url = kw["steps"][0]["url"]
                return {"extracts": {"announcements": {"blocked": url == announcements.SOURCE,
                    "topics": [TOPIC] if url == announcements.RELAY else [],
                    "posts": [post()] if url == TOPIC else []}}}
            return {}
        result = announcements.check({"schema": 1, "announcements": []}, call, NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"][0]["status"], "blocked")
        self.assertEqual(result["sources"][1]["status"], "ok")
        self.assertEqual(result["announcements"][0]["confidence"], "low")
        self.assertEqual(result["announcements"][0]["primary_source_url"], URL)
        self.assertTrue(result["announcements"][0]["source_url"].startswith(TOPIC))
        self.assertEqual(announcements.overrides([], result, NOW), [])
        self.assertEqual(len(calls), 5)

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


class RelayConfirmationTests(unittest.TestCase):
    def document(self):
        entry = announcements.parse(post())
        entry.update(source_url=TOPIC + '#announcement-1234567890', primary_source_url=URL,
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
                announcements.confirm(self.document(), TOPIC + '#announcement-1234567890', reset, NOW)
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

    def test_search_is_bounded_and_topic_walls_are_recorded_without_following_untrusted_links(self):
        visited = []
        topics = [TOPIC + str(index) for index in range(5)]
        def call(op, **kwargs):
            if kwargs.get('action') == 'open':
                return {'window_id': 'lease'}
            if op == 'browser.op':
                url = kwargs['steps'][0]['url']
                visited.append(url)
                data = {'blocked': url != announcements.RELAY, 'posts': []}
                if url == announcements.RELAY:
                    data['topics'] = ['https://example.invalid/reset', *topics]
                return {'extracts': {'announcements': data}}
            return {}
        result = announcements.check({'schema': 1, 'announcements': []}, call, NOW)
        self.assertEqual(visited, [announcements.SOURCE, announcements.RELAY, *topics[:3]])
        self.assertTrue(all(row['status'] == 'blocked' for row in result['sources'][2:]))
        self.assertEqual(result['announcements'], [])

    def test_rediscovery_preserves_confirmation_and_successful_notice(self):
        document = self.document()
        url = document['announcements'][0]['source_url']
        announcements.confirm(document, url, '2030-07-01T17:00:00Z', NOW)
        document['announcements'][0]['notice_sent_at'] = NOW
        def call(op, **kwargs):
            if kwargs.get('action') == 'open':
                return {'window_id': 'lease'}
            if op == 'browser.op':
                current = kwargs['steps'][0]['url']
                return {'extracts': {'announcements': {'blocked': current == announcements.SOURCE,
                    'topics': [TOPIC], 'posts': [post()] if current == TOPIC else []}}}
            return {}
        result = announcements.check(document, call, NOW + announcements.INTERVAL)
        self.assertEqual(result['announcements'][0]['confidence'], 'confirmed')
        self.assertEqual(result['announcements'][0]['notice_sent_at'], NOW)


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

    def test_relay_cadence_is_independent_of_primary_retry(self):
        visited = []
        document = {'schema': 1, 'announcements': [], 'relay_checked_at': NOW - 100}
        first = announcements.check(document, self.browser(visited, True), NOW)
        self.assertEqual(visited, [announcements.SOURCE])
        announcements.check(first, self.browser(visited, True), NOW + 8 * 3600)
        self.assertEqual(visited, [announcements.SOURCE, announcements.SOURCE, announcements.RELAY])

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
            relay = RelayConfirmationTests().document()['announcements'][0]
            relay['notice_sent_at'] = NOW
            primary = announcements.parse(post())
            records = [relay, primary]
            if reverse:
                records.reverse()
            with patch.object(announcements.subprocess, 'run') as publish:
                announcements.notify_pending({'announcements': records}, 'fixture-notify', NOW + 1)
                publish.assert_not_called()
            self.assertEqual(primary['notice_sent_at'], NOW)

    def test_new_posts_share_canonical_notice_key_and_all_confidences_notify(self):
        relay = RelayConfirmationTests().document()['announcements'][0]
        primary = announcements.parse(post())
        low = announcements.parse(post('Reset day!', url=URL + '1'))
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
