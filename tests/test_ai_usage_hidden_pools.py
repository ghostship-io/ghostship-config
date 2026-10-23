"""Antigravity third-party routes and limits must not reach any output."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import main
import catalog
import ranking
import pools
import snapshot
from metrics import SourceResult


class HiddenPoolTests(unittest.TestCase):
    def test_only_antigravity_third_party_routes_are_hidden(self):
        for model in ('claude-opus-test', 'gpt-oss-test', 'bridge/gpt-test'):
            self.assertFalse(pools.visible_route('antigravity', model))
            self.assertTrue(pools.visible_route('other', model))
        self.assertTrue(pools.visible_route('antigravity', 'gemini-test'))
        for window in ({'quotaId': '3p-5h'}, {'quota': '3p-weekly'},
                       {'applies_to': ['claude', 'gpt']}, {'model': 'claude-opus-test'}):
            self.assertFalse(pools.visible_window('antigravity', window))
            self.assertTrue(pools.visible_window('other', window))

    def test_ranking_excludes_third_party_models_before_scoring(self):
        result = ranking.rank_models(models=[
            ranking.ModelRecord('antigravity', 'claude-opus-test'),
            ranking.ModelRecord('antigravity', 'gemini-test')],
            catalog=catalog.Catalog({}), quota_windows={}, free_models=set(), now=1000)
        self.assertNotIn('claude-opus-test', [row.model for row in result])
        self.assertIn('gemini-test', [row.model for row in result])

    def test_snapshot_drops_candidates_windows_and_inventory_mentions(self):
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
        self.assertNotIn('3p-5h', json.dumps(value))
        self.assertIn('gemini-5h', json.dumps(value))
        # The main projection adds entitlements separately; it must use the
        # same visibility filter as the snapshot itself.
        published = main.build_snapshot([], [hidden], {}, 1000, measured_windows=windows)
        self.assertNotIn('3p-5h', json.dumps(published))
        self.assertIn('gemini-5h', json.dumps(published))

    def test_metrics_drop_raw_limits_and_models_but_keep_gemini(self):
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
        self.assertNotIn('3p-5h', text)
        self.assertNotIn('claude-opus-test', text)
        self.assertIn('gemini-5h', text)


if __name__ == '__main__':
    unittest.main()
