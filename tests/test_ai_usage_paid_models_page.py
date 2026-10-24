"""Paid models page: what is picked next, and why every other route is or is not picked."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import model_selection
from metrics import MetricWriter

PAGE = ROOT / 'modules/self-hosted/siem/dashboards/paid-models.json'
NOW = 1767268800000
SECONDS = NOW / 1000


def call(panel, name, *args):
    script = 'const helpers={};const context={handlebars:{registerHelper:(key,fn)=>helpers[key]=fn}};'
    script += "new Function('context'," + json.dumps(panel['options']['helpers']) + ')(context);'
    script += 'console.log(JSON.stringify(helpers[' + json.dumps(name) + '](...' + json.dumps(list(args)) + ')));'
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def helper(panel, name, rows, now=NOW):
    return call(panel, name, rows, now)


def walk(panels):
    for panel in panels:
        yield panel
        yield from walk(panel.get('panels') or [])


def route(provider, model, position, category='worker', billing='subscription', state='available', left=None,
          pace=None, pace_state='unknown', window='weekly', overspent='false', reset=None, trust='trusted'):
    labels = {'category': category, 'provider': provider, 'model': model, 'display_name': model, 'effort': '',
              'state': state, 'trust': trust, 'billing': billing, 'overspent': overspent, 'pace_state': pace_state,
              'window': window, 'sensitivity_sensitive': 'true'}
    rows = [{**labels, 'field': 'position', 'value': position}]
    for field, value in (('left', left), ('pace', pace), ('resetAt', reset)):
        if value is not None:
            rows.append({**labels, 'field': field, 'value': value})
    return rows


def census(provider, count, category='worker', state='available', trust='trusted', overspent='false',
           pace_state='on_pace', sensitive='true', reason='every applicable window has headroom'):
    return {'category': category, 'provider': provider, 'state': state, 'trust': trust, 'overspent': overspent,
            'pace_state': pace_state, 'sensitivity_sensitive': sensitive, 'reason': reason, 'field': 'census',
            'value': count}


class PaidPageShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}

    def test_identity_navigation_and_top_band_order(self):
        self.assertEqual((self.page['uid'], self.page['title']), ('ghostship-paid-models', 'Paid models'))
        self.assertEqual([link['title'] for link in self.page['links']], ['Providers', 'Paid models', 'Free models'])
        top = [p for p in self.page['panels'] if p['type'] != 'row']
        # The orchestrator is one row across the page; the worker lane and the reasons list share the next row.
        self.assertEqual([p['id'] for p in top], [201, 260, 263, 261, 262])
        self.assertEqual([p['id'] for p in sorted(top, key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))],
                         [201, 260, 263, 261, 262])
        self.assertEqual({v['name'] for v in self.page['templating']['list']}, {'provider'})
        self.assertNotRegex(json.dumps(self.page), r'(?i)\b(3d|frontier|chief|delegate|bulk)\b')

    def test_every_table_is_in_the_one_collapsed_evidence_row(self):
        rows = [p for p in self.page['panels'] if p['type'] == 'row']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['collapsed'])
        self.assertEqual([p['id'] for p in rows[0]['panels']], [270, 250, 241, 242])
        for panel in self.page['panels']:
            self.assertNotIn(panel['type'], ('table', 'logs'))
        self.assertGreater(rows[0]['gridPos']['y'], max(p['gridPos']['y'] for p in self.page['panels'] if p['type'] != 'row'))

    def test_top_panels_are_scoped_dynamic_text_without_inner_scroll(self):
        for panel_id in (260, 261, 262):
            panel = self.panels[panel_id]
            self.assertNotIn('repeat', panel)
            self.assertTrue(panel['transparent'])
            self.assertEqual(panel['options']['renderMode'], 'allRows')
            self.assertNotRegex(panel['options']['styles'], r'overflow(?:-y)?\s*:\s*(?:auto|scroll)')
            # A name is never cut short: it wraps.
            self.assertNotRegex(panel['options']['styles'], r'text-overflow\s*:\s*ellipsis')
            css = re.sub(r'@(?:media|container)[^{]*\{', '', panel['options']['styles'])
            for head in re.findall(r'(?:^|[}\n])\s*([^{}@]+)\{', css):
                for selector in head.split(','):
                    self.assertRegex(selector.strip(), r'^\.gx', selector)
            self.assertIn('latest snapshot', panel['options']['defaultContent'])

    def test_queries_read_fresh_series_for_the_scope_and_the_selected_route(self):
        tolerance = '> scalar(max(timestamp(ghostship_ai_collection_duration_seconds))) - 90'
        for panel_id in (260, 261, 262):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn(tolerance, expr, panel_id)
            self.assertNotIn('== scalar(max(timestamp', expr, panel_id)
            # A pruned (obsolete) route is published with picker_eligible="false": the paid scope is its billing class.
            self.assertIn('billing!~"free|promotion"', expr, panel_id)
            self.assertNotIn('picker_eligible', expr, panel_id)
            self.assertIn('provider!="openrouter"', expr, panel_id)
            self.assertIn('provider!="opencode-free"', expr, panel_id)
            self.assertIn('provider!="pi"', expr, panel_id)
            self.assertIn('provider=~"$provider"', expr, panel_id)
            self.assertNotIn('billing=~"free|promotion"', expr, panel_id)
        for panel_id in (260, 261, 263):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn('on(category, provider, model, effort) ghostship_ai_picker_model_selected', expr)
            for field in ('position', 'left', 'pace', 'resetAt'):
                self.assertIn('"field", "%s"' % field, expr)
        for panel_id in (260, 261, 262, 263):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn('"field", "census"', expr)
            self.assertIn('"reason", "pick", "reason", "pick: .*"', expr)
        self.assertIn('category="orchestrator"', self.panels[263]['targets'][0]['expr'])
        self.assertNotIn('category="worker"', self.panels[263]['targets'][0]['expr'])
        self.assertIn('category="worker"', self.panels[261]['targets'][0]['expr'])
        self.assertNotIn('category="orchestrator"', self.panels[261]['targets'][0]['expr'])

    def test_opencode_free_is_not_a_paid_route_or_a_paid_filter_choice(self):
        variable = self.page['templating']['list'][0]
        self.assertIn('provider!="opencode-free"', variable['definition'])
        self.assertIn('provider!="opencode-free"', self.panels[270]['targets'][0]['expr'])

    def test_pi_is_absent_from_dashboard_queries(self):
        for variable in self.page['templating']['list']:
            self.assertIn('provider!="pi"', variable.get('definition', ''))
        for panel in walk(self.page['panels']):
            for target in panel.get('targets', []):
                query = target.get('expr', '')
                if 'provider!=' in query:
                    self.assertIn('provider!="pi"', query)

    def test_the_ordering_measure_is_named_paced_availability_where_it_is_drawn(self):
        self.assertIn('Paced Availability', self.panels[261]['options']['content'])

    def test_the_t3_strip_names_the_issue_that_ends_its_permanent_partial(self):
        rows = [{'field': 'collected', 'value': SECONDS}, {'source': 't3', 'field': 'info', 'status': 'partial', 'reason': 'unsupported'}]
        status = {r['name']: r for r in helper(self.panels[201], 'sourceHealth', rows)}
        self.assertEqual(status['T3 providers']['text'], 'unavailable · unsupported · #470')

    def test_source_failures_and_stale_collection_are_visible_above_models(self):
        panel = self.panels[201]
        rows = [{'field': 'collected', 'value': SECONDS},
                {'source': 't3_usage', 'field': 'info', 'status': 'error', 'reason': 'timeout'},
                {'source': 't3', 'field': 'info', 'status': 'ok'}]
        status = {row['name']: row for row in helper(panel, 'sourceHealth', rows)}
        self.assertEqual(status['T3 usage']['text'], 'unavailable · timeout')
        self.assertEqual(status['T3 providers']['text'], 'current')
        self.assertTrue(all(row['state'] == 'error' for row in helper(panel, 'sourceHealth', rows, NOW + 601000)))
        self.assertEqual(helper(panel, 'sourceHealth', [], NOW)[0]['text'], 'missing collection timestamp')


class LaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = next(p for p in walk(json.loads(PAGE.read_text())['panels']) if p['id'] == 261)

    def rows(self, rows, lane='paid', limit=0):
        return call(self.panel, 'modelRows', rows, NOW, lane, limit)['rows']

    def test_providers_follow_the_picker_order_and_the_first_pickable_route_is_next(self):
        rows = (route('antigravity', 'a', 9, state='exhausted', left=0, pace_state='spent', window='quota')
                + route('claude', 'c', 11, state='reserved')
                + route('ollama', 'o', 5, left=.5, pace=-12.34, pace_state='behind')
                + route('codex', 'x', 7, left=.21, pace=-63.85, pace_state='far_behind', overspent='true'))
        lane = self.rows(rows)
        self.assertEqual([r['provider'] for r in lane], ['ollama', 'codex', 'antigravity', 'claude'])
        # The rank is the picker's own position among all workers, so a paid worker reads 5th behind the free routes.
        self.assertEqual([r['first'] for r in lane], [True, False, False, False])
        self.assertEqual([r['next'] for r in lane], [False, False, False, False])
        self.assertEqual([r['rank'] for r in lane], [5, 7, 9, 11])
        by = {r['provider']: r for r in lane}
        self.assertEqual((by['ollama']['kind'], by['ollama']['word'], by['ollama']['paText']), ('warn', 'Behind pace', '−12.3'))
        self.assertEqual((by['codex']['kind'], by['codex']['word']), ('bad', 'Overspent'))
        self.assertEqual((by['antigravity']['kind'], by['antigravity']['word']), ('out', 'Out of quota'))
        self.assertEqual((by['claude']['kind'], by['claude']['word']), ('held', 'Held for review'))

    def test_a_provider_with_routes_but_no_selected_route_stays_visible_and_says_why(self):
        rows = [census('grok', 5, state='exhausted', overspent='true', pace_state='spent', reason='quota_exhausted')]
        lane = self.rows(rows)
        self.assertEqual((lane[0]['name'], lane[0]['noRoute'], lane[0]['word'], lane[0]['next']), ('Grok', True, 'All out of quota', False))
        self.assertEqual(lane[0]['census']['text'], '0 of 5 pickable')
        self.assertTrue(lane[0]['many'])
        self.assertFalse(lane[0]['pace'])

    def test_the_obsolete_label_wins_and_the_reason_text_is_the_fallback(self):
        labelled = census('p', 1, reason='superseded by a newer family model')
        labelled['obsolete'] = 'true'
        text = census('p', 1, state='unavailable', reason='not offered by the T3 instance (deprecated in the catalog)')
        absent = census('p', 1, state='unavailable', reason='not offered by the T3 instance')
        keys = lambda rows: {p['key']: p['count'] for p in self.rows(rows)[0]['census']['parts']}
        self.assertEqual(keys([labelled]), {'obsolete': 1})
        self.assertEqual(keys([text]), {'obsolete': 1})
        self.assertEqual(keys([absent]), {'unavailable': 1})
        self.assertIn('obsolete, reason', self.panel['targets'][0]['expr'])

    def test_pickable_routes_with_no_selected_route_are_unknown_not_out(self):
        lane = self.rows([census('opencode-free', 34), census('opencode-free', 1, trust='untrusted')])
        self.assertEqual((lane[0]['kind'], lane[0]['word'], lane[0]['capacity'], lane[0]['out']), ('unk', '', 'no route selected', False))
        self.assertFalse(lane[0]['next'])

    def test_every_route_is_counted_once_by_the_first_reason_that_applies(self):
        cases = {
            'excluded': dict(state='excluded', trust='excluded', reason='model_excluded'),
            'obsolete': dict(state='unavailable', reason='not offered by the T3 instance (deprecated in the catalog)'),
            'unavailable': dict(state='unavailable', reason='not offered by the T3 instance'),
            'cooling': dict(state='unavailable', reason='cooling down in the free pool until 2026-10-25T00:00:02Z'),
            'exhausted': dict(state='exhausted', overspent='true', pace_state='spent', reason='quota_exhausted'),
            'untrusted': dict(trust='untrusted', overspent='true'),
            'held': dict(state='reserved', reason='current shared weekly review headroom is unknown'),
            'overspent': dict(overspent='true', pace_state='far_behind'),
            'pickable': dict(),
        }
        rows = [census('p', 1, **kw) for kw in cases.values()]
        parts = self.rows(rows)[0]['census']['parts']
        self.assertEqual({p['key']: p['count'] for p in parts}, {key: 1 for key in cases})
        self.assertEqual([p['key'] for p in parts],
                         ['pickable', 'overspent', 'exhausted', 'untrusted', 'held', 'cooling', 'unavailable', 'obsolete', 'excluded'])
        self.assertEqual(self.rows(rows)[0]['census']['pickable'], 1)

    def test_the_stacked_bar_widths_sum_to_the_whole_and_one_route_has_no_bar(self):
        rows = [census('ollama', 8), census('ollama', 14, state='exhausted', reason='quota_exhausted'),
                census('ollama', 1, state='excluded', trust='excluded', reason='model_excluded'),
                census('codex', 1, reason='pick')] + route('codex', 'x', 3, left=.4, pace_state='on_pace')
        by = {r['provider']: r for r in self.rows(rows)}
        self.assertAlmostEqual(sum(p['pct'] for p in by['ollama']['census']['parts']), 100, delta=.2)
        self.assertEqual(by['ollama']['census']['skipped'], '14 out of quota · 1 excluded by policy')
        self.assertTrue(by['ollama']['many'])
        self.assertFalse(by['codex']['many'])

    def test_unknown_capacity_never_reads_as_a_full_bar(self):
        inferred = self.rows(route('google', 'g', 8, billing='free', left=1, window='inferred', pace_state='on_pace'), 'free')[0]
        self.assertEqual((inferred['kind'], inferred['capacity'], inferred['leftText']), ('unk', 'no limit seen', ''))
        self.assertFalse(inferred['pace'])
        silent = self.rows(route('claude', 'c', 1, category='orchestrator'), 'orchestrator')[0]
        self.assertEqual((silent['kind'], silent['capacity']), ('unk', 'capacity unknown · #465'))
        self.assertIn('{{#if (eq kind "unk")}}', self.panel['options']['content'])

    def test_only_a_long_window_is_paced_a_daily_window_shows_its_reset_alone(self):
        daily = self.rows(route('openrouter', 'm', 2, billing='free', left=1, window='daily', pace_state='on_pace',
                                reset=SECONDS + 3 * 3600), 'free')[0]
        self.assertEqual((daily['pace'], daily['paceLong'], daily['when']), (True, False, 'resets in 3h 0m'))
        weekly = self.rows(route('ollama', 'm', 1, left=.5, window='weekly', pace_state='behind', pace=-9))[0]
        self.assertEqual((weekly['pace'], weekly['paceLong'], weekly['paKnown']), (True, True, True))
        unknown = self.rows(route('codex', 'm', 1, left=.5, window='weekly'))[0]
        self.assertEqual((unknown['paceLong'], unknown['paKnown']), (True, False))
        self.assertIn('pace unknown', self.panel['options']['content'])

    def test_sensitivity_limit_is_noted_only_when_it_splits_a_provider(self):
        rows = [census('a', 3, sensitive='false'), census('b', 2, sensitive='false'), census('b', 2, sensitive='true')]
        by = {r['provider']: r for r in self.rows(rows)}
        self.assertFalse(by['a']['census']['partial'])
        self.assertTrue(by['b']['census']['partial'])
        self.assertEqual((by['a']['census']['limited'], by['b']['census']['limited']), (3, 2))

    def test_lanes_split_by_category(self):
        rows = route('claude', 'o', 1, category='orchestrator') + route('codex', 'w', 2) + [census('codex', 1, category='orchestrator')]
        # Only the picker's first orchestrator is the orchestrator: its other candidates are not listed.
        self.assertEqual([r['provider'] for r in self.rows(rows, 'orchestrator')], ['claude'])
        self.assertEqual([r['provider'] for r in self.rows(rows, 'paid')], ['codex'])

    def test_the_configured_orchestrator_alone_is_counted_in_the_summary_and_the_reasons(self):
        rows = (route('claude', 'o', 1, category='orchestrator') + route('codex', 'o', 2, category='orchestrator')
                + [census('claude', 1, category='orchestrator'), census('codex', 1, category='orchestrator'), census('ollama', 2)])
        summary = call(self.panel, 'modelSummary', rows, NOW, 'paid')
        self.assertEqual(summary['pickable'], {'count': 3, 'of': 3})
        self.assertEqual(summary['orchestrator']['name'], 'Claude')
        reasons = call(self.panel, 'modelReasons', rows)
        self.assertEqual(reasons['total'], 3)

    def test_a_paid_worker_says_where_the_picker_tries_it(self):
        rows = route('ollama', 'o', 4, left=.5, pace=-12.34, pace_state='behind')
        worker = call(self.panel, 'modelSummary', rows, NOW, 'paid')['worker']
        self.assertIn('tried 4th, after the free routes', worker['detail'])

    def test_the_reset_text_says_back_for_a_spent_route_and_resets_for_a_live_one(self):
        spent = self.rows(route('a', 'm', 1, state='exhausted', left=0, pace_state='spent', reset=SECONDS + 6 * 3600))[0]
        live = self.rows(route('b', 'm', 2, left=.5, reset=SECONDS + 90 * 60))[0]
        self.assertEqual((spent['when'], live['when']), ('back in 6h 0m', 'resets in 1h 30m'))


class SummaryAndReasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}

    def test_summary_names_the_next_picks_and_counts_pickable_and_skipped(self):
        rows = (route('claude', 'opus', 1, category='orchestrator') + route('ollama', 'o', 5, left=.5, pace=-12, pace_state='behind')
                + [census('claude', 1, category='orchestrator', pace_state='unknown'),
                   census('ollama', 3), census('ollama', 4, state='exhausted', reason='quota_exhausted'),
                   census('codex', 2, overspent='true', pace_state='far_behind'), census('claude', 1, state='reserved')])
        summary = call(self.panels[260], 'modelSummary', rows, NOW, 'paid')
        self.assertEqual((summary['orchestrator']['name'], summary['worker']['name']), ('Claude', 'Ollama'))
        self.assertEqual(summary['pickable'], {'count': 4, 'of': 11})
        self.assertEqual((summary['skipped']['count'], summary['skipped']['text']), (7, '4 out of quota · 2 overspent'))

    def test_no_pickable_route_says_none_available_instead_of_naming_one(self):
        rows = route('a', 'm', 1, state='exhausted', left=0, pace_state='spent')
        summary = call(self.panels[260], 'modelSummary', rows, NOW, 'paid')
        self.assertIsNone(summary['worker'])
        self.assertIn('None available', self.panels[260]['options']['content'])

    def test_reasons_count_every_category_and_name_the_providers_behind_each_count(self):
        rows = [census('codex', 7, overspent='true', pace_state='far_behind'), census('claude', 1, category='orchestrator'),
                census('ollama', 14, state='exhausted', reason='quota_exhausted'),
                census('grok', 5, state='exhausted', reason='quota_exhausted'),
                census('x', 4, sensitive='false')]
        reasons = call(self.panels[262], 'modelReasons', rows, NOW)
        self.assertEqual(reasons['total'], 31)
        self.assertEqual(reasons['limited'], 4)
        by = {r['key']: r for r in reasons['list']}
        self.assertEqual((by['exhausted']['count'], by['exhausted']['who']), (19, 'Ollama 14 · Grok 5'))
        self.assertEqual(by['overspent']['count'], 7)
        self.assertEqual(max(r['width'] for r in reasons['list']), 100)
        self.assertEqual(call(self.panels[262], 'modelReasons', [], NOW)['empty'], True)

    def test_a_missing_tool_loop_proof_is_drawn_as_unknown_not_as_a_count(self):
        content = self.panels[262]['options']['content']
        self.assertIn('No tool-loop proof', content)
        self.assertIn('not reported yet · #479', content)
        self.assertIn('class="bar hatch"', content)


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}

    def test_the_route_table_lists_every_candidate_with_its_reason(self):
        table = self.panels[270]
        expr = table['targets'][0]['expr']
        self.assertIn('ghostship_ai_picker_model_position{category=~"orchestrator|worker"', expr)
        self.assertIn('provider=~"$provider"', expr)
        self.assertEqual(table['transformations'][0]['options']['renameByName']['reason'], 'Reason')

    def test_tokens_per_pass_are_formatted_like_t3(self):
        panel = self.panels[250]
        labels = {'provider': 'example', 'model': 'm', 'effort': 'low', 'effort_option': 'effort',
                  'aa_date': '2026-10-23T00:00:00Z', 'source': 'bench', 'evidence_state': 'ok'}
        for raw, text in ((1203481, '1.2M'), (1961703, '2M'), (4200, '4.2k'), (950, '950'), (3.2e9, '3.2B')):
            rows = [{**labels, 'field': 'info', 'value': 1}, {**labels, 'field': 'tokens_per_pass', 'value': raw}]
            self.assertEqual(helper(panel, 'qualityRows', rows)[0]['tokens'], text)


    def test_unmeasured_aa_has_neither_source_link_nor_date(self):
        panel=self.panels[250]
        row={'provider':'example','model':'unmeasured','effort':'low','aa_date':'2026-10-23T00:00:00Z',
             'field':'info','value':1}
        model=helper(panel,'qualityRows',[row])[0]
        self.assertFalse(model['hasAA'])
        self.assertEqual(model['aaDate'],'')
        self.assertIn('{{#if this.hasAA}}<a href=',panel['options']['content'])


    def test_quality_table_uses_published_scores_and_preserves_missing_evidence(self):
        panel=self.panels[250]
        labels={'provider':'example','model':'model','display_name':'Example','effort':'low',
                'effort_option':'effort','aa_date':'2026-10-23T00:00:00Z',
                'source':'bench + work','evidence_state':'ok'}
        rows=[{**labels,'field':field,'value':value} for field,value in {
            'info':1,'rank':1,'overall':72.34,'aa':70,'observed':80,'n':5,'passed':4,
            'observed_weight':1/11,'tokens_per_pass':150,'median_seconds':120,'date':1767268800}.items()]
        value=helper(panel,'qualityRows',rows)[0]
        self.assertEqual((value['overall'],value['aa'],value['observed'],value['n']),('72.3','70','80',5))
        self.assertEqual(value['passes'],'4/5')
        self.assertEqual(value['quota'],'—')
        self.assertEqual(value['findings'],'—')
        self.assertFalse(value['provisional'])
        empty=helper(panel,'qualityRows',[{**labels,'evidence_state':'producer_unavailable','field':'info','value':1}])[0]
        self.assertEqual((empty['overall'],empty['observed'],empty['passes']),('—','—','no evidence yet'))
        self.assertTrue(empty['evidenceMissing'])


    def test_quality_collapses_efforts_and_only_offers_comparison_when_observations_differ(self):
        import model_quality
        sys.path.insert(0, str(ROOT / 'tests'))
        from test_ai_usage_model_quality import candidate,rounds,NOW
        active=candidate()
        spent=candidate('spent')
        spent['capacity']['remaining_ratio']=0
        records=rounds(n=5)+rounds(effort='high',n=5)
        for different in (False,True):
            if different:records[-1]['wall_seconds']=300
            result=model_quality.build([active,spent],records,NOW)
            selection=model_selection.build({'candidates':[active,spent]},[])
            model_quality.annotate(result,selection)
            rows=[{**labels,'field':name.removeprefix('ghostship_ai_quality_'),'value':value}
                  for name,labels,value in model_quality.samples(result)]
            models=helper(self.panels[250],'qualityModels',rows)
            self.assertEqual(len(models),2)
            chosen=next(model for model in models if model['model']=='model')
            self.assertTrue(chosen['selected'])
            self.assertEqual(chosen['selectionReason'],'Best eligible worker model of example')
            self.assertEqual(chosen['compare'],different)
            spent_model=next(model for model in models if model['model']=='spent')
            self.assertFalse(spent_model['selected'])
            self.assertEqual(spent_model['selectionReason'],'Allowance spent')
            self.assertFalse(chosen['hasFindings'])
            self.assertFalse(chosen['hasQuota'])
        self.assertIn('data-quality-controls',self.panels[250]['options']['content'])


    def test_quality_hook_builds_controls_after_grafana_sanitization(self):
        subprocess.run(['node',str(ROOT/'tests/fixtures/ai-usage/quality-hook-dom.cjs'),str(PAGE)],check=True)
        self.assertNotIn('<input',self.panels[250]['options']['content'])


    def test_public_model_identity_is_not_changed_by_metric_rendering(self):
        source={'provider':'example','model':'family/model','display_name':'Example',
            'available':True,'native':{'mapped':True,'provider_instance_id':'example','model_id':'family/model'},
            'capacity':{},'quality_score':80}
        value=model_selection.build({'candidates':[source]},[])
        writer=MetricWriter()
        for name,labels,number in model_selection.samples(value):writer.add(name,labels,number)
        self.assertIn('model="family/model"',writer.render())
        self.assertNotIn('model="family_model"',writer.render())



if __name__ == "__main__":
    unittest.main()
