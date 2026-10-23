"""Antigravity unused routes stay out of selection; unused limits remain visible."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import main
import catalog
import ranking
import quota
import pools
import snapshot
from metrics import SourceResult


class UnusedPoolTests(unittest.TestCase):
    def test_only_antigravity_third_party_routes_are_hidden(self):
        for model in ('claude-opus-test', 'gpt-oss-test', 'bridge/gpt-test'):
            self.assertFalse(pools.usable_route('antigravity', model))
            self.assertTrue(pools.usable_route('other', model))
        self.assertTrue(pools.usable_route('antigravity', 'gemini-test'))
        for window in ({'quotaId': '3p-5h'}, {'quota': '3p-weekly'},
                       {'applies_to': ['claude', 'gpt']}, {'model': 'claude-opus-test'}):
            self.assertTrue(pools.not_used_window('antigravity', window))
            self.assertFalse(pools.not_used_window('other', window))

    def test_ranking_excludes_third_party_models_before_scoring(self):
        result = ranking.rank_models(models=[
            ranking.ModelRecord('antigravity', 'claude-opus-test'),
            ranking.ModelRecord('antigravity', 'gemini-test')],
            catalog=catalog.Catalog({}), quota_windows={}, free_models=set(), now=1000)
        self.assertNotIn('claude-opus-test', [row.model for row in result])
        self.assertIn('gemini-test', [row.model for row in result])

    def test_snapshot_keeps_unused_windows_but_excludes_candidates(self):
        hidden = SimpleNamespace(provider='antigravity', model='claude-opus-test')
        windows = [dict(provider='antigravity', model='*', kind='session',
                        quotaId=quota, usedRatio=0.5, observedAtEpoch=1000,
                        resetEpoch=2000, durationSeconds=1000)
                   for quota in ('3p-5h', 'gemini-5h')]
        value = snapshot.build_snapshot(now=1000, sources=[], ranked=[hidden],
            measured_windows=windows, inventory=[('antigravity', hidden.model)],
            inferred_windows=[{'provider': 'antigravity', 'applies_to': ['claude', 'gpt']}])
        self.assertEqual(value['candidates'], [])
        self.assertNotIn(hidden.model, json.dumps(value))
        self.assertIn('3p-5h', json.dumps(value))
        self.assertTrue(next(w for w in value['quota']['accounts']['antigravity'] if w['quota_id']=='3p-5h')['not_used'])
        self.assertIn('gemini-5h', json.dumps(value))
        # The main projection adds entitlements separately; it must use the
        # same usage-only policy as the snapshot itself.
        published = main.build_snapshot([], [hidden], {}, 1000, measured_windows=windows)
        self.assertIn('3p-5h', json.dumps(published))
        self.assertTrue(next(w for w in published['quota']['entitlements'] if w['canonical_quota']=='3p-5h')['not_used'])
        self.assertIn('gemini-5h', json.dumps(published))

    def test_fable_weekly_limits_remain_usage_only_without_pace(self):
        windows = [dict(provider='claude', model='*', kind='weekly', quotaId=identifier,
                        usedRatio=.5, resetEpoch=2000, observedAtEpoch=1000, durationSeconds=604800)
                   for identifier in ('seven_day_fable', 'seven_day')]
        value = main.build_snapshot([], [], {}, 1000, measured_windows=windows)
        unused = next(w for w in value['quota']['accounts']['claude'] if w['quota_id']=='seven_day_fable')
        self.assertTrue(unused['not_used'])
        samples = [r for r in snapshot.account_window_samples(value) if r[1].get('not_used')=='true']
        self.assertTrue(samples)
        self.assertTrue(any(r[0].endswith('_remaining_ratio') and r[2]==.5 for r in samples))
        self.assertTrue(any(r[1].get('state')=='not_used' for r in samples))
        self.assertFalse(any('expected' in r[0] or 'pace_delta' in r[0] for r in samples))
        self.assertFalse(quota.is_paced_window(windows[0]))
        self.assertTrue(quota.is_paced_window(windows[1]))
        self.assertTrue(all(r[1]['quota'] != 'seven_day_fable' for r in quota.quota_pace_samples(windows, 1000)))

    def test_usage_metrics_keep_unused_limits_and_exclude_selection(self):
        labels = [dict(provider='antigravity', model='*', quota='3p-5h'),
                  dict(provider='antigravity', model='claude-opus-test'),
                  dict(provider='antigravity', model='*', quota='gemini-5h')]
        metrics = [('ghostship_ai_quota_used_ratio', label, .5) for label in labels]
        source = SourceResult(source='antigravity', status='ok', metrics=metrics,
            windows=[dict(provider='antigravity', model='*', kind='session',
                          quota_id='3p-5h', used_ratio=.5, reset_at=2000, observed_at=1000)])
        stale_selection = main.model_selection.build({'candidates': [{
            'provider': 'antigravity', 'model': 'claude-opus-test', 'available': True,
            'capacity': {'remaining_ratio': 1}, 'native': {'mapped': True,
                'provider_instance_id': 'antigravity', 'model_id': 'claude-opus-test'}}]}, [])
        text = main.render([source], metrics, 1000, .1, {'model_selection': stale_selection})
        self.assertIn('3p-5h', text)
        third_party = [line for line in text.splitlines() if '3p-5h' in line]
        self.assertTrue(all('not_used="true"' in line for line in third_party))
        self.assertFalse(any('pace_delta' in line or 'expected_' in line for line in third_party))
        self.assertNotIn('ghostship_ai_picker_model_info{', text)
        self.assertIn('claude-opus-test', text)
        self.assertIn('gemini-5h', text)
        self.assertFalse(pools.usable_route('claude', 'claude-fable-test'))


if __name__ == '__main__':
    unittest.main()
