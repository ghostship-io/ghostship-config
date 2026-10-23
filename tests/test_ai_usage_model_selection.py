"""The picker and provider cards must agree on availability and selection."""
import importlib.util
from pathlib import Path
import unittest
import sys

PATH = Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector/model_selection.py'
sys.path.insert(0, str(PATH.parent))
spec = importlib.util.spec_from_file_location('picker_selection', PATH)
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


def candidate(provider, model, quality=80, remaining=1, trust='trusted'):
    return {'provider': provider, 'model': model, 'available': True,
            'quality_score': quality, 'trust': {'worker': {'level': trust}},
            'native': {'mapped': True, 'provider_instance_id': provider, 'model_id': model},
            'capacity': {'remaining_ratio': remaining}}


class SelectionTests(unittest.TestCase):
    def build(self, rows):
        return selection.build({'generated_at': '2026-10-23T12:00:00Z', 'candidates': rows},
                               [{'instance_id': 'codex', 'model': 'reviewer'}])

    def test_orchestrator_is_also_worker_and_quality_picks_default(self):
        value = self.build([candidate('other', 'fast', 70), candidate('codex', 'reviewer', 90)])
        self.assertEqual(set(value['providers']['codex']), {'orchestrator', 'worker', 'selected', 'pools'})
        self.assertEqual(value['default_worker'], {'instanceId': 'codex', 'model': 'reviewer'})
        self.assertEqual(value['orchestrator'][0]['native'], value['default_worker'])
        self.assertEqual(value['worker'][0]['native'], value['default_worker'])

    def test_effort_comes_from_each_native_models_supported_choices(self):
        for identifier, choices, expected, review_expected in (
            ('reasoningEffort', ['high', 'low', 'ultra', 'max'], 'high', 'high'),
            ('effort', ['ultracode', 'max', 'ultrathink', 'medium'], 'max', 'medium'),
            ('reasoningEffort', ['low', 'high'], 'high', 'high'),
            ('variant', ['none', 'thinking'], 'thinking', 'thinking')):
            with self.subTest(option=identifier, choices=choices):
                row = candidate('codex', 'reviewer')
                row['native']['options'] = [{'id': identifier, 'values': choices}]
                result = self.build([row])
                options = [{'id': identifier, 'value': expected}]
                self.assertEqual(result['default_worker']['options'], options)
                self.assertEqual(result['orchestrator'][0]['native']['options'],
                                 [{'id': identifier, 'value': review_expected}])
        self.assertEqual(selection.effort_options([{'id': 'thinking', 'type': 'boolean'}]),
                         [{'id': 'thinking', 'value': True}])
        self.assertEqual(selection.effort_options([{'id': 'serviceTier', 'values': ['priority']}]), [])
        self.assertEqual(selection.effort_options([{'id': 'effort', 'values': ['unknown']}]), [])

    def test_spent_best_is_retained_unavailable_and_returns_after_reset(self):
        rows = [candidate('codex', 'reviewer', 95, 0), candidate('other', 'fast', 80)]
        value = self.build(rows)
        self.assertEqual(value['default_worker']['model'], 'fast')
        self.assertEqual(value['orchestrator'][0]['state'], 'exhausted')
        rows[0]['capacity']['remaining_ratio'] = .5
        self.assertEqual(self.build(rows)['default_worker']['model'], 'reviewer')

    def test_excluded_omitted_and_backup_follows_trusted(self):
        value = self.build([candidate('one', 'backup', 99, trust='backup'),
                            candidate('two', 'ordinary', 60),
                            candidate('three', 'excluded', 100, trust='excluded')])
        self.assertEqual([row['model'] for row in value['worker']], ['ordinary', 'backup', 'excluded'])
        self.assertFalse(value['worker'][-1]['available'])

    def test_new_untiered_route_still_obeys_identity_exclusion(self):
        row = candidate('example', 'excluded-route')
        row['trust'] = {}
        evidence = {'identities': {'models': {'excluded-model': {'routes': ['example/excluded-route']}}},
                    'policy': {'model_trust': {'entries': [
                        {'model': 'excluded-model', 'level': 'excluded', 'task_types': ['*']}]}}}
        result = selection.build({'candidates': [row]}, [], evidence=evidence)
        self.assertEqual(result['worker'][0]['trust_level'], 'excluded')
        self.assertFalse(result['worker'][0]['available'])
        self.assertIsNone(result['default_worker'])

    def test_policy_missing_an_excluded_identity_cannot_publish_selection(self):
        import main
        evidence = {'policy': {'roles': {'orchestrator': [{'instance_id': 'one', 'model': 'a'}]},
                              'model_selection': {'categories': list(selection.CATEGORIES)},
                              'model_trust': {'entries': [{'model': 'excluded-model', 'level': 'excluded'}]}},
                    'identities': [{'id': 'other'}]}
        self.assertFalse(selection.policy_ready(evidence))
        snapshot = main.build_snapshot([], [], {}, 1000, outcomes=evidence)
        self.assertNotIn('model_selection', snapshot)
        evidence['identities'].append({'id': 'excluded-model'})
        self.assertTrue(selection.policy_ready(evidence))

    def test_freshness_and_partial_state_reach_consumers(self):
        value = selection.build({'generated_at': '2026-10-23T12:00:00Z', 'partial': True}, [])
        self.assertEqual(value['generated_at'], '2026-10-23T12:00:00Z')
        self.assertTrue(value['partial'])
        self.assertIsNone(value['default_worker'])

    def test_native_disabled_model_cannot_be_favorite_or_default(self):
        row = candidate('codex', 'reviewer')
        row['native']['available'] = False
        result = self.build([row])
        self.assertFalse(result['worker'][0]['available'])
        self.assertIsNone(result['default_worker'])

    def test_standard_tier_is_explicit_when_supported(self):
        options = selection.native_options([
            {'id': 'serviceTier', 'values': ['standard', 'priority']},
            {'id': 'fastMode', 'type': 'boolean'},
            {'id': 'reasoningEffort', 'values': ['medium', 'high']}])
        self.assertEqual(options, [{'id': 'reasoningEffort', 'value': 'high'},
                                   {'id': 'serviceTier', 'value': 'standard'},
                                   {'id': 'fastMode', 'value': False}])

    def test_custom_reset_is_named_and_reported_reset_is_retained(self):
        import reset_overrides
        from metrics import SourceResult
        import snapshot
        import main
        from datetime import datetime
        at = datetime.fromisoformat('2026-10-23T12:00:00+00:00').timestamp()
        measured = {'provider': 'codex', 'quotaId': 'weekly', 'kind': 'weekly',
                    'usedRatio': .5, 'resetEpoch': at + 600000,
                    'durationSeconds': 604800, 'observedAtEpoch': at}
        results = [SourceResult('t3', 'ok', windows=[measured.copy()])]
        override = {'provider': 'codex', 'quota_id': 'weekly', 'reset_at': '2026-10-23T17:00:00Z'}
        reset_overrides.apply(results, [override], at)
        inputs = main.ranking_inputs(results, main.catalog_module.Catalog({}), {},
                                     results[0].windows, now=at)
        window = snapshot._window_record(inputs['windows']['codex'][0], at)
        limit = selection.limiting_window([window], '2026-10-23T12:00:00Z')
        self.assertEqual(limit['reset_label'], 'custom reset')
        self.assertEqual(limit['reset_source'], 'custom')
        self.assertEqual(limit['reset_at'], override['reset_at'])
        self.assertEqual(limit['provider_reset_at'], snapshot._iso(at + 600000))
        self.assertEqual(limit['seconds_to_reset'], 18000)
        self.assertEqual(limit['pace_state'], 'ahead')
        gauges = snapshot.account_window_samples({'quota': {'accounts': {'codex': [window]}}})
        self.assertTrue(gauges)
        self.assertTrue(all('custom reset' in labels['label'] for _, labels, _ in gauges))
        expired = [SourceResult('t3', 'ok', windows=[measured.copy()])]
        reset_overrides.apply(expired, [override], at + 18001)
        self.assertEqual(expired[0].windows[0], measured)

    def test_short_windows_gate_but_never_become_display_limiting_window(self):
        short = {'kind': 'session', 'remaining_ratio': 0, 'duration_seconds': 18000,
                 'seconds_to_reset': 9000, 'quota_id': 'session'}
        weekly = {'kind': 'weekly', 'remaining_ratio': .7, 'duration_seconds': 604800,
                  'seconds_to_reset': 302400, 'quota_id': 'week'}
        row = candidate('codex', 'reviewer', remaining=0)
        row['windows'] = [short, weekly]
        value = self.build([row])
        selected = value['worker'][0]
        self.assertFalse(selected['available'])
        self.assertEqual(selected['limiting_window']['kind'], 'weekly')
        self.assertEqual(selected['limiting_window']['pace_state'], 'ahead')
        self.assertEqual(selected['limiting_window']['pace_delta'], 20)
        self.assertIsNone(selection.limiting_window([short], '2026-10-23T12:00:00Z'))

    def test_daily_hourly_minute_and_short_inferred_never_limit(self):
        for kind in ('daily', 'hourly', 'minute', 'inferred', 'quota', 'credits'):
            with self.subTest(kind=kind):
                self.assertIsNone(selection.limiting_window(
                    [{'kind': kind, 'duration_seconds': 3600, 'remaining_ratio': 0}],
                    '2026-10-23T12:00:00Z'))

    def test_free_route_close_to_best_quality_leads_subscription(self):
        free = candidate('free-provider', 'free', quality=85)
        free['access'] = {'billing': 'free'}
        value = self.build([candidate('codex', 'reviewer', quality=90), free])
        self.assertEqual(value['worker'][0]['model'], 'free')
        self.assertEqual(value['default_worker']['model'], 'free')

    def test_far_behind_follows_other_routes_in_same_trust_level(self):
        behind = candidate('one', 'strong', quality=99)
        behind['windows'] = [{'kind': 'weekly', 'remaining_ratio': .2,
                              'duration_seconds': 604800, 'seconds_to_reset': 302400}]
        value = self.build([behind, candidate('two', 'ordinary', quality=70)])
        self.assertEqual(value['default_worker']['model'], 'ordinary')

    def test_subpoint_quality_differences_are_not_alphabetical_ties(self):
        weaker = candidate('example', 'a-model', quality=85)
        stronger = candidate('example', 'z-model', quality=85)
        for row, prior in ((weaker, .849), (stronger, .851)):
            row.update(quality_p0=prior, quality_n=0, quality_s=0)
        self.assertEqual(self.build([weaker, stronger])['default_worker']['model'], 'z-model')

    def test_free_margin_uses_unrounded_quality(self):
        paid = candidate('example', 'paid', quality=81)
        paid.update(quality_p0=.8096, quality_n=0, quality_s=0)
        free = candidate('example', 'free', quality=71)
        free.update(quality_p0=.7094, quality_n=0, quality_s=0, access={'billing': 'free'})
        self.assertEqual(self.build([paid, free])['default_worker']['model'], 'paid')

    def test_each_provider_pool_keeps_an_independent_order_and_choice(self):
        rows = [candidate('example', 'best', 95, 0), candidate('example', 'next', 90),
                candidate('example', 'separate', 80)]
        for row in rows[:2]:
            row['pool'] = {'id': 'example:all', 'label': 'All', 'basis': 'audit'}
        rows[2]['pool'] = {'id': 'example:separate', 'label': 'Separate', 'basis': 'audit'}
        provider = self.build(rows)['providers']['example']
        self.assertEqual(provider['pools']['example:all']['selected']['worker']['model'], 'next')
        self.assertEqual(provider['pools']['example:separate']['selected']['worker']['model'], 'separate')
        self.assertEqual([r['pool_position'] for r in provider['pools']['example:all']['worker']], [1, 2])


if __name__ == '__main__':
    unittest.main()
