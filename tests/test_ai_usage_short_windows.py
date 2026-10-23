"""Short quota windows gate availability while long windows alone supply pace."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import quota
import ranking
import snapshot

NOW = 1800000000.0
WEEK = 604800


def window(kind, used=.8, duration=3600):
    return ranking.QuotaWindow(kind, used, NOW + duration / 2,
                               duration_seconds=duration, observed_at=NOW, quota_id=kind)


class ShortWindowTests(unittest.TestCase):
    def test_short_windows_have_no_pace_or_expected_usage(self):
        for kind in ('session', 'hourly', 'daily', 'minute', 'rolling'):
            with self.subTest(kind=kind):
                value = window(kind)
                self.assertIsNone(quota.window_pace(value, NOW))
                self.assertEqual(ranking._pace(value, NOW, .2), (None, None))
                self.assertEqual(snapshot._pace_record(value, NOW, .2), (None, None))

    def test_account_short_window_keeps_capacity_and_reset_but_no_line(self):
        for remaining in (.2, 0):
            with self.subTest(remaining=remaining):
                record = snapshot._window_record(window('session', used=1-remaining), NOW)
                gauges = snapshot.account_window_samples({'quota': {'accounts': {'example': [record]}}})
                values = {name: (labels, value) for name, labels, value in gauges}
                self.assertAlmostEqual(values['ghostship_ai_account_window_remaining_ratio'][1], remaining)
                self.assertIn('ghostship_ai_account_window_reset_timestamp_seconds', values)
                self.assertNotIn('ghostship_ai_account_window_expected_remaining_ratio', values)
                expected = 'on_pace' if remaining else 'spent'
                self.assertEqual(values['ghostship_ai_account_window_pace_state'][0]['state'], expected)

    def test_unpaced_entitlement_retains_its_current_quota_reading(self):
        measured = {'provider': 'example', 'kind': 'session', 'quotaId': 'session',
                    'usedRatio': .8, 'resetEpoch': NOW + 1800,
                    'durationSeconds': 3600, 'observedAtEpoch': NOW}
        entry = quota.entitlements([measured], NOW)[0]
        self.assertTrue(entry['readings'][0]['usable'])
        self.assertEqual(entry['display']['used_ratio'], .8)
        self.assertIsNone(entry['display']['expected_used_ratio'])
        self.assertIsNone(entry['display']['pace_delta_ratio'])

    def test_short_capacity_binding_does_not_supply_the_weekly_pace(self):
        short = window('session', .9)
        weekly = window('weekly', .3, WEEK)
        detail = ranking._capacity_detail([short, weekly], NOW)
        self.assertAlmostEqual(detail['remaining'], .1)
        self.assertEqual(detail['binding'], short)
        self.assertEqual(detail['paceBinding'], weekly)
        self.assertAlmostEqual(detail['paceValue'], .2)

    def test_model_row_uses_the_weekly_windows_own_usage_for_pace(self):
        short = window('session', .9)
        weekly = window('weekly', .3, WEEK)
        entry = ranking.RankedModel('bulk', 'example', 'model', 1, 80, 80, .1, 1800, True,
                                    windows=(short, weekly), pace=.2, pace_binding=weekly,
                                    capacity_binding=short)
        row = snapshot._candidate('example', 'model', [entry], NOW, None, {})
        self.assertEqual(row['capacity']['remaining_ratio'], .1)
        self.assertEqual(row['capacity']['expected_used_ratio'], .5)
        self.assertEqual(row['capacity']['measured_used_ratio'], .3)
        self.assertEqual(row['capacity']['pace_state'], 'ahead')

    def test_exhausted_short_window_still_blocks_the_route(self):
        detail = ranking._capacity_detail([window('session', 1), window('weekly', .3, WEEK)], NOW)
        self.assertEqual(detail['remaining'], 0)

    def test_weekly_and_monthly_retain_pace(self):
        for kind, duration in (('weekly', WEEK), ('monthly', 30*86400), ('inferred', WEEK)):
            with self.subTest(kind=kind):
                pace = quota.window_pace(window(kind, .3, duration), NOW)
                self.assertIsNotNone(pace)
                self.assertAlmostEqual(pace['pace_delta_ratio'], .2)


if __name__ == '__main__':
    unittest.main()
