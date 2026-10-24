"""The picker and provider cards must agree on availability and selection."""
import importlib.util
from pathlib import Path
import unittest
import sys
from collector_fixture import state_args

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

    def test_provider_role_policy_keeps_review_authority_without_workers(self):
        rows = [candidate('review-only','opus',80), candidate('review-only','fable',99),
                candidate('codex','reviewer',85)]
        evidence = {'policy': {'model_selection': {'provider_roles': {'review-only':['orchestrator']}}}}
        reviews = [{'instance_id':'review-only','model':'opus'}, {'instance_id':'codex','model':'reviewer'}]
        result = selection.build({'candidates':rows},reviews,evidence=evidence)
        group = result['providers']['review-only']
        self.assertEqual(group['worker'], [])
        self.assertIsNone(group['selected']['worker'])
        self.assertEqual(group['selected']['orchestrator']['model'], 'opus')
        self.assertEqual(result['default_worker']['model'], 'reviewer')
        self.assertFalse(any(row['provider']=='review-only' for row in result['worker']))
        self.assertEqual({row['native']['model'] for row in result['role_exclusions']}, {'opus','fable'})
        for pool in group['pools'].values():
            self.assertEqual(pool['worker'], [])
            self.assertIsNone(pool['selected']['worker'])

    def test_excluded_pool_keeps_the_other_provider_pool(self):
        rows = [candidate('antigravity', model) for model in ('claude-opus-5-5','gpt-6.1-sol','gemini-4-argon')]
        result = selection.build({'candidates':rows}, [], evidence={
            'policy':{'model_selection':{'excluded_pools':['antigravity:3p']}}})
        self.assertEqual([row['model'] for row in result['worker']], ['gemini-4-argon'])
        self.assertEqual(set(result['providers']['antigravity']['pools']), {'antigravity:gemini'})

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
        self.assertEqual(self.build(rows)['providers']['codex']['selected']['worker']['model'], 'reviewer')
        rows[1]['capacity']['remaining_ratio'] = .2
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

    def test_five_hour_spent_model_stays_listed_and_is_the_display_binding(self):
        short = {'kind': 'session', 'remaining_ratio': 0, 'duration_seconds': 18000,
                 'seconds_to_reset': 9000, 'quota_id': 'session'}
        weekly = {'kind': 'weekly', 'remaining_ratio': .7, 'duration_seconds': 604800,
                  'seconds_to_reset': 302400, 'quota_id': 'week'}
        row = candidate('codex', 'reviewer', remaining=0)
        row['windows'] = [short, weekly]
        value = self.build([row])
        selected = value['worker'][0]
        self.assertFalse(selected['available'])
        self.assertEqual(selected['limiting_window']['kind'], 'session')
        self.assertEqual(selected['limiting_window']['pace_state'], 'spent')
        self.assertIsNone(selected['limiting_window']['pace_delta'])
        self.assertEqual(len(value['worker']),1)
        self.assertIsNone(value['default_worker'])
        self.assertTrue(any(name=='ghostship_ai_picker_model_selected' and number==1
                            for name,labels,number in selection.samples(value)))

    def test_short_binding_windows_are_never_paced(self):
        for kind in ('daily', 'hourly', 'minute', 'inferred', 'quota', 'credits'):
            with self.subTest(kind=kind):
                window=selection.limiting_window(
                    [{'kind': kind, 'duration_seconds': 3600, 'remaining_ratio': .2}],
                    '2026-10-23T12:00:00Z')
                self.assertEqual(window['remaining_ratio'],.2)
                self.assertIsNone(window['pace_delta'])
                self.assertEqual(window['pace_state'],'on_pace')

    def test_free_route_close_to_best_quality_leads_subscription(self):
        free = candidate('free-provider', 'free', quality=85)
        free['access'] = {'billing': 'free'}
        value = self.build([candidate('codex', 'reviewer', quality=90), free])
        self.assertEqual(value['worker'][0]['model'], 'free')
        self.assertEqual(value['default_worker']['model'], 'reviewer')
        self.assertIsNone(next(r for r in value['worker'] if r['model'] == 'free')['native'])

    def test_every_eligible_free_provider_publishes_one_choice_without_t3_favorites(self):
        rows = []
        for provider in ('opencode', 'nvidia', 'groq'):
            for model, quality in (('best', 90), ('alternate', 70), ('spent', 99)):
                row = candidate(provider, model, quality, remaining=0 if model == 'spent' else .6)
                row['native'] = {}  # The free runtime is outside T3.
                row['access'] = {'billing': 'free'}
                rows.append(row)
        result = self.build(rows)
        self.assertEqual(result['free_selected'], {p: p + ':best' for p in ('opencode', 'nvidia', 'groq')})
        self.assertIsNone(result['default_worker'])
        self.assertTrue(all(group['selected']['worker'] is None for group in result['providers'].values()))
        published = [(labels['provider'], labels['model']) for name, labels, number in selection.samples(result)
                     if name == 'ghostship_ai_picker_model_selected' and number == 1]
        self.assertCountEqual(published, [(p, 'best') for p in ('opencode', 'nvidia', 'groq')])
        rows[0]['available'] = False
        self.assertEqual(self.build(rows)['free_selected']['opencode'], 'opencode:alternate')

    def test_lane_order_and_default_follow_live_capacity_without_fixed_provider_order(self):
        one=candidate('one','strong',99,remaining=.2)
        two=candidate('two','other',70,remaining=.8)
        two['windows']=[{'kind':'session','duration_seconds':18000,'remaining_ratio':.8}]
        value=self.build([one,two])
        self.assertEqual(value['default_worker']['model'],'other')
        self.assertEqual(value['worker'][0]['limiting_window']['kind'],'session')
        two['capacity']['remaining_ratio']=0
        two['windows'][0]['remaining_ratio']=0
        self.assertEqual(self.build([one,two])['default_worker']['model'],'strong')
        two['capacity']['remaining_ratio']=1
        two['windows'][0]['remaining_ratio']=1
        self.assertEqual(self.build([one,two])['default_worker']['model'],'other')

    def test_untiered_gemini_inherits_its_live_family_limit_and_stays_listed_at_zero(self):
        row=candidate('antigravity','gemini-example',remaining=None)
        window={'kind':'session','quota_id':'gemini-5h','remaining_ratio':.15,
                'duration_seconds':18000,'check_at':'2026-10-23T12:00:00Z',
                'reset_at':'2026-10-23T13:00:00Z','applies_to':['gemini']}
        unrelated={**window,'quota_id':'3p-5h','remaining_ratio':0,'applies_to':['claude','gpt']}
        snapshot={'generated_at':'2026-10-23T12:00:00Z','candidates':[row],
                  'quota':{'accounts':{'antigravity':[window,unrelated]}}}
        value=selection.build(snapshot,[])
        self.assertEqual(value['worker'][0]['remaining_ratio'],.15)
        self.assertEqual(value['worker'][0]['limiting_window']['quota_id'],'gemini-5h')
        self.assertIsNotNone(value['default_worker'])
        window['remaining_ratio']=0
        value=selection.build(snapshot,[])
        self.assertEqual(len(value['worker']),1)
        self.assertFalse(value['worker'][0]['available'])
        self.assertIsNone(value['default_worker'])
        self.assertTrue(any(name=='ghostship_ai_picker_model_selected' and number==1
                            for name,labels,number in selection.samples(value)))

    def test_far_behind_follows_other_routes_in_same_trust_level(self):
        behind = candidate('one', 'strong', quality=99)
        behind['windows'] = [{'kind': 'weekly', 'remaining_ratio': .2,
                              'duration_seconds': 604800, 'seconds_to_reset': 302400}]
        value = self.build([behind, candidate('two', 'ordinary', quality=70)])
        self.assertEqual(value['default_worker']['model'], 'ordinary')

    def test_owner_named_dated_build_wins_without_inheriting_alias_outcomes(self):
        alias = candidate('ollama', 'deepseek-v4.1-flash', quality=74)
        dated = candidate('ollama', 'deepseek-v4.1-flash:1017', quality=53)
        for row, n, accepted in ((alias, 40, 32), (dated, 5, 3)):
            row['native'].update(provider_instance_id='opencode',
                                 model_id='ollama-cloud/' + row['model'])
            row.update(quality_p0=.5, quality_n=n, quality_s=accepted)
        evidence = {'policy': {'model_selection': {'worker_builds': {
            'ollama': 'ollama-cloud/deepseek-v4.1-flash:1017'}}}}
        value = selection.build({'candidates': [alias, dated]}, [], evidence=evidence)
        expected = {'instanceId': 'opencode', 'model': 'ollama-cloud/deepseek-v4.1-flash:1017'}
        self.assertEqual(value['providers']['ollama']['selected']['worker'], expected)
        self.assertEqual(value['default_worker'], expected)
        by_model = {row['model']: row for row in value['worker']}
        self.assertEqual((by_model[alias['model']]['quality_n'], by_model[alias['model']]['quality_s']), (40,32))
        self.assertEqual((by_model[dated['model']]['quality_n'], by_model[dated['model']]['quality_s']), (5,3))
        self.assertGreater(by_model[alias['model']]['quality_p'], by_model[dated['model']]['quality_p'])
        self.assertTrue(by_model[alias['model']]['available'])
        self.assertFalse(by_model[alias['model']]['selection_eligible'])

    def test_missing_or_spent_named_build_cannot_fall_back_to_alias(self):
        for dated_remaining in (None, 0):
            with self.subTest(dated_remaining=dated_remaining):
                alias = candidate('ollama', 'alias', quality=99)
                alias['native']['model_id'] = 'ollama-cloud/alias'
                rows = [alias, candidate('other', 'available', quality=60)]
                if dated_remaining is not None:
                    dated = candidate('ollama', 'dated:1017', remaining=dated_remaining)
                    dated['native']['model_id'] = 'ollama-cloud/dated:1017'
                    rows.append(dated)
                evidence = {'policy': {'model_selection': {'worker_builds': {
                    'ollama': 'ollama-cloud/dated:1017'}}}}
                value = selection.build({'candidates': rows}, [], evidence=evidence)
                self.assertIsNone(value['providers']['ollama']['selected']['worker'])
                self.assertEqual(value['default_worker']['model'], 'available')

    def test_build_preferences_reach_published_selection_through_real_entrypoint(self):
        import json
        import tempfile
        from unittest.mock import patch
        import main
        evidence = {'policy': {'roles': {'orchestrator': [{'instance_id':'codex', 'model':'reviewer'}]},
                              'model_selection': {'categories': list(selection.CATEGORIES)}},
                    'identities': [{'id':'example'}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefs = root / 'preferences.json'
            builds = {'ollama':'ollama-cloud/deepseek-v4.1-flash:1017'}
            prefs.write_text(json.dumps({'schema':'ghostship.model-selection-preferences/v1',
                                         'worker_builds':builds}))
            with patch.object(main,'collect',return_value=([],[],{})), \
                 patch.object(main,'read_outcomes',return_value=evidence), \
                 patch.object(main.model_quality,'read_evidence',return_value=([],'no_evidence')), \
                 patch.object(main,'log'):
                self.assertEqual(main.main(state_args(root, ['--model-selection-preferences',str(prefs),
                    '--output',str(root/'metrics.prom'),'--snapshot',str(root/'routing.json'),
                    '--aa-catalog',str(root/'missing-catalog.json'),'--now','1000'])),0)
            published = json.loads((root/'routing.json').read_text())
            self.assertEqual(published['model_selection']['worker_builds'],builds)
            prefs.write_text('{}')
            with self.assertRaises(ValueError):
                selection.load_worker_builds(str(prefs))

    def test_worker_build_choice_preserves_separate_orchestrator_authority(self):
        alias = candidate('codex','reviewer',quality=90)
        worker = candidate('codex','dated:1017',quality=70)
        evidence = {'policy': {'model_selection': {'worker_builds': {'codex':'dated:1017'}}}}
        value = selection.build({'candidates':[alias,worker]},
            [{'instance_id':'codex','model':'reviewer'}],evidence=evidence)
        self.assertEqual(value['providers']['codex']['selected']['orchestrator']['model'],'reviewer')
        self.assertEqual(value['providers']['codex']['selected']['worker']['model'],'dated:1017')

    def test_collector_publishes_and_retries_picker_after_t3_connection_failure(self):
        import json
        import tempfile
        from types import ModuleType
        from unittest.mock import Mock, patch
        import main

        class T3Error(RuntimeError):
            pass

        bridge_module = ModuleType('ghostship_t3.bridge')
        bridge_module.Bridge = Mock()
        bridge_module.T3Error = T3Error
        picker_module = ModuleType('ghostship_t3.model_selection')
        picker_module.reconcile = Mock()
        modules = {'ghostship_t3': ModuleType('ghostship_t3'),
                   'ghostship_t3.bridge': bridge_module,
                   'ghostship_t3.model_selection': picker_module}
        evidence = {'policy': {'roles': {'orchestrator': []},
                              'model_selection': {'categories': list(selection.CATEGORIES)}},
                    'identities': [{'id': 'example'}]}
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules), \
             patch.object(main, 'collect', return_value=([], [], {})), \
             patch.object(main, 'read_outcomes', return_value=evidence), \
             patch.object(main.model_quality, 'read_evidence', return_value=([], 'no_evidence')), \
             patch.object(main, 'read_session_token', return_value=''), \
             patch.object(main, 'resolve_t3_base_url', return_value='http://127.0.0.1:1'), \
             patch.object(main, 'log') as log:
            root = Path(directory)
            args = state_args(root, ['--reconcile-picker', '--now', '1000',
                                    '--projection', str(root / 'projection.json')])
            for cause in (ConnectionRefusedError(111, 'Connection refused'), TimeoutError()):
                error = T3Error('transport details must not enter the log')
                error.__cause__ = cause
                picker_module.reconcile.side_effect = error
                self.assertEqual(main.main(args), 0)
                self.assertTrue((root / 'output.json').is_file())
                self.assertEqual(json.loads((root / 'projection.json').read_text()),
                                 json.loads((root / 'snapshot.json').read_text()))
                self.assertFalse((root / 'picker-state.json').exists())
            self.assertNotIn('transport details', str(log.call_args_list))
            picker_module.reconcile.side_effect = None
            picker_module.reconcile.return_value = {'state': 'updated', 'favorite_changes': 1}
            self.assertEqual(main.main(args), 0)
            self.assertEqual(picker_module.reconcile.call_count, 3)
            # A malformed settings response or authentication failure must still fail visibly.
            picker_module.reconcile.side_effect = T3Error('unexpected response')
            with self.assertRaises(T3Error):
                main.main(args)

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

    def test_picker_positions_do_not_count_routes_the_picker_cannot_offer(self):
        external = candidate('example', 'inference-only', 95)
        external['native'] = {'mapped': False}
        native = candidate('example', 'native', 90)
        result = self.build([external, native])
        self.assertEqual(result['default_worker']['model'], 'native')
        row = next(row for row in result['worker'] if row['model'] == 'native')
        self.assertEqual(row['provider_position'], 2)
        self.assertEqual((row['picker_provider_position'], row['picker_pool_position']), (1, 1))
        published = {name: number for name, labels, number in selection.samples(result)
                     if labels['model'] == 'native'}
        self.assertEqual(published['ghostship_ai_picker_model_provider_position'], 1)
        self.assertEqual(published['ghostship_ai_picker_model_pool_position'], 1)


if __name__ == '__main__':
    unittest.main()
