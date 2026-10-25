"""Free models page: the same graphics as Paid models, scoped to free routes and generated from one source."""
import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'modules/self-hosted/siem/dashboards/free-workers.json'
PAID = ROOT / 'modules/self-hosted/siem/dashboards/paid-models.json'
NOW = 1767268800000


def call(panel, name, *args):
    script = 'const helpers={};const context={handlebars:{registerHelper:(key,fn)=>helpers[key]=fn}};'
    script += "new Function('context'," + json.dumps(panel['options']['helpers']) + ')(context);'
    script += 'console.log(JSON.stringify(helpers[' + json.dumps(name) + '](...' + json.dumps(list(args)) + ')));'
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def walk(panels):
    for panel in panels:
        yield panel
        yield from walk(panel.get('panels') or [])


def census(provider, count, state='available', trust='trusted', sensitive='false', reason='pick', category='worker'):
    return {'category': category, 'provider': provider, 'state': state, 'trust': trust, 'overspent': 'false',
            'pace_state': 'on_pace', 'sensitivity_sensitive': sensitive, 'reason': reason, 'field': 'census', 'value': count}


def route(provider, model, position, left=1, window='inferred', state='available'):
    labels = {'category': 'worker', 'provider': provider, 'model': model, 'display_name': model, 'effort': '',
              'state': state, 'trust': 'trusted', 'billing': 'free', 'overspent': 'false', 'pace_state': 'on_pace',
              'window': window, 'sensitivity_sensitive': 'false'}
    rows = [{**labels, 'field': 'position', 'value': position}]
    if left is not None:
        rows.append({**labels, 'field': 'left', 'value': left})
    return rows


class FreePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}

    def test_committed_dashboards_match_the_generator(self):
        cmd = [sys.executable, str(ROOT / 'scripts/generate-model-dashboards.py'), '--check']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f'a dashboard differs from the generator:\n{result.stderr}')

    def test_page_metadata_and_fleet_navigation(self):
        self.assertEqual((self.page['uid'], self.page['title'], self.page['timezone']),
                         ('ghostship-free-workers', 'Free models', 'utc'))
        self.assertFalse(self.page['editable'])
        self.assertEqual([link['title'] for link in self.page['links']], ['Providers', 'Paid models', 'Free models'])
        self.assertEqual({v['name'] for v in self.page['templating']['list']}, {'provider'})

    def test_top_band_is_graphics_and_every_table_is_in_the_collapsed_row(self):
        top = [p for p in self.page['panels'] if p['type'] != 'row']
        self.assertEqual([p['id'] for p in top], [201, 260, 261, 262])
        rows = [p for p in self.page['panels'] if p['type'] == 'row']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['collapsed'])
        self.assertEqual([p['id'] for p in rows[0]['panels']], [270, 250, 241, 242])
        self.assertTrue(all(p['type'] != 'table' for p in top))

    def test_every_query_is_free_scoped_and_never_paid(self):
        queries = json.dumps([t for p in walk(self.page['panels']) if p['id'] != 201 for t in p.get('targets', [])]
                             + self.page['templating']['list'])
        self.assertIn('billing=~\\"free|promotion\\"', queries)
        for forbidden in ('opencode-go', 'subscription', 'picker_eligible=\\"true\\"', 'orchestrator_model'):
            self.assertNotIn(forbidden, queries)
        for panel_id in (260, 261, 262):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn('billing=~"free|promotion"', expr)
            self.assertIn('provider=~"$provider"', expr)
            self.assertIn('> scalar(max(timestamp(ghostship_ai_collection_duration_seconds))) - 90', expr)
        variable = self.page['templating']['list'][0]
        self.assertIn('billing=~"free|promotion"', variable['definition'])

    def test_opencode_free_routes_are_filed_under_the_provider_their_model_names(self):
        # OpenCode Free is an instance, not a provider: its routes belong to the provider in their model id.
        for panel_id in (260, 261, 262, 270):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn('provider="opencode-free",model=~"$provider/.*"', expr, panel_id)
            self.assertIn('provider="opencode-free",model!~".*/.*"', expr, panel_id)
            self.assertIn('provider!="opencode-free",provider=~"$provider"', expr, panel_id)
        for panel_id in (260, 261, 262):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn('"provider", "$1", "model", "([^/]+)/.*"', expr, panel_id)
            # a bare model id is an OpenCode Zen route and follows the Zen provider filter
            self.assertIn('"provider", "opencode", "model", "[^/]+"', expr, panel_id)
        variable = self.page['templating']['list'][0]
        self.assertIn('provider!="opencode-free"', variable['definition'])
        self.assertEqual(variable['regex'], '/provider="([^"]+)"/')

    def test_only_the_owner_approved_free_workers_are_lane_rows(self):
        lane = self.panels[261]['targets'][0]['expr']
        selectors = [part.split('}')[0] for part in lane.split('ghostship_ai_picker_model_selected{')[1:]]
        self.assertTrue(selectors)
        for selector in selectors:
            self.assertIn('approved_free="true"', selector)
        census_only = self.panels[262]['targets'][0]['expr']
        self.assertNotIn('approved_free="true"', census_only)
        self.assertIn('approved_free', census_only)

    def test_a_provider_with_only_public_pool_routes_is_counted_but_not_listed(self):
        rows = [{**census('kilo', 8), 'billing': 'free', 'approved_free': 'false'},
                {**census('cloudflare-workers-ai', 2), 'billing': 'free', 'approved_free': 'true'}]
        lane = call(self.panels[261], 'modelRows', rows, NOW, 'free', 0)['rows']
        self.assertEqual([r['provider'] for r in lane], ['cloudflare-workers-ai'])

    def test_a_free_route_off_the_approved_list_is_counted_as_the_public_pool(self):
        rows = [census('cloudflare-workers-ai', 2), {**census('cohere', 5), 'billing': 'free', 'approved_free': 'false'},
                {**census('groq', 1), 'billing': 'free', 'approved_free': 'true'}]
        reasons = call(self.panels[262], 'modelReasons', rows)
        by = {item['key']: item['count'] for item in reasons['list']}
        self.assertEqual(by, {'pickable': 3, 'public': 5})

    def test_an_account_window_that_reads_zero_makes_the_lane_row_out_of_quota_with_its_reset(self):
        rows = route('nvidia', 'openai/gpt-oss-20b', 3, left=.9995, window='inferred') + [
            {'account': 'nvidia', 'quota_id': 'inferred:exhausted', 'evidence': 'inferred', 'kind': 'inferred', 'field': 'acctLeft', 'value': 0},
            {'account': 'nvidia', 'quota_id': 'inferred:exhausted', 'evidence': 'inferred', 'kind': 'inferred', 'field': 'acctReset',
             'value': NOW / 1000 + 3600},
            {'account': 'nvidia', 'quota_id': 'inferred:1h', 'evidence': 'inferred', 'kind': 'inferred', 'field': 'acctLeft', 'value': .9995}]
        row = call(self.panels[261], 'modelRows', rows, NOW, 'free', 0)['rows'][0]
        self.assertEqual((row['kind'], row['word'], row['capacity'], row['when']), ('out', 'Out of quota', '0% left', 'back in 1h 0m'))
        self.assertEqual(row['acctNote'], 'account window spent · estimated')

    def test_an_opencode_free_route_of_unknown_billing_off_the_approved_list_is_public_pool(self):
        rows = [{**census('cloudflare-workers-ai', 2), 'billing': 'unknown', 'approved_free': 'false', 'pool': 'opencode-free:default'},
                {**census('grok', 4), 'billing': 'unknown', 'approved_free': 'false', 'pool': 'grok:credits'},
                {**census('opencode', 3), 'billing': 'free', 'approved_free': 'true', 'pool': 'opencode-free:default'}]
        reasons = call(self.panels[262], 'modelReasons', rows)
        by = {item['key']: item['count'] for item in reasons['list']}
        self.assertEqual(by, {'pickable': 7, 'public': 2})

    def test_a_spent_account_blocks_a_provider_that_has_no_selected_route(self):
        rows = [{**census('opencode', 14), 'billing': 'free', 'approved_free': 'true'},
                {'account': 'opencode', 'quota_id': 'inferred:exhausted', 'evidence': 'inferred', 'kind': 'inferred', 'field': 'acctLeft', 'value': 0},
                {'account': 'opencode', 'quota_id': 'inferred:exhausted', 'evidence': 'inferred', 'kind': 'inferred', 'field': 'acctReset',
                 'value': NOW / 1000 + 3600}]
        row = call(self.panels[261], 'modelRows', rows, NOW, 'free', 0)['rows'][0]
        self.assertEqual((row['kind'], row['word'], row['noRoute'], row['when']), ('out', 'Out of quota', True, 'back in 1h 0m'))
        self.assertEqual(row['acctNote'], 'account window spent · estimated')

    def test_the_calibration_state_of_the_selected_route_is_shown(self):
        rows = route('openrouter', 'cohere/north-mini-code:free', 2, left=1) + [
            {'provider': 'openrouter', 'model': 'cohere_north-mini-code:free', 'state': 'warn', 'field': 'calibration', 'value': 1}]
        row = call(self.panels[261], 'modelRows', rows, NOW, 'free', 0)['rows'][0]
        self.assertEqual((row['calib']['state'], row['calib']['word']), ('warn', 'calibration warning'))

    def test_the_free_page_has_no_orchestrator_tile_or_lane(self):
        content = self.panels[260]['options']['content'] + self.panels[261]['options']['content']
        self.assertNotIn('Next orchestrator', content)
        self.assertNotIn('data-lane="orchestrator"', content)
        self.assertIn('Next free worker', content)
        self.assertIn('public tasks only', content)
        self.assertIn('filled by #467', content)

    def rows(self, rows, limit=0):
        return call(self.panels[261], 'modelRows', rows, NOW, 'free', limit)['rows']

    def test_a_free_provider_with_every_route_blocked_stays_visible_with_its_reasons(self):
        rows = [census('opencode', 40, state='unavailable', reason='not offered by the T3 instance (deprecated in the catalog)'),
                census('opencode', 1, state='unavailable', reason='cooling down in the free pool until 2026-10-25T00:00:02Z'),
                census('opencode', 4, state='unavailable', reason='not offered by the T3 instance'),
                census('groq', 3)] + route('groq', 'm', 1)
        lane = self.rows(rows)
        self.assertEqual([r['provider'] for r in lane], ['groq', 'opencode'])
        blocked = lane[1]
        self.assertEqual((blocked['name'], blocked['noRoute'], blocked['word']), ('OpenCode Zen', True, 'All obsolete'))
        self.assertEqual(blocked['census']['skipped'], '1 cooling down · 4 not offered · 40 obsolete')
        self.assertEqual(blocked['census']['text'], '0 of 45 pickable')

    def test_a_free_route_that_saw_no_limit_is_unknown_never_one_hundred_percent(self):
        row = self.rows(route('google', 'gemini', 1, left=1, window='inferred'))[0]
        self.assertEqual((row['kind'], row['capacity'], row['leftText']), ('unk', 'no limit seen', ''))
        self.assertFalse(row['pace'])
        real = self.rows(route('openrouter', 'm', 1, left=.4, window='daily'))[0]
        self.assertEqual((real['capacity'], real['kind']), ('40% left', 'ok'))

    def test_summary_counts_free_routes_and_names_the_next_free_worker(self):
        rows = route('groq', 'm', 1) + [census('groq', 3), census('opencode', 5, state='unavailable', reason='not offered')]
        summary = call(self.panels[260], 'modelSummary', rows, NOW, 'free')
        self.assertIsNone(summary['orchestrator'])
        self.assertEqual(summary['worker']['name'], 'Groq')
        self.assertEqual((summary['pickable'], summary['skipped']['count']), ({'count': 3, 'of': 8}, 5))


class ModelDashboardGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('model_dashboards', ROOT / 'scripts/generate-model-dashboards.py')
        cls.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.generator)

    def with_evidence(self, change):
        evidence = copy.deepcopy(self.generator.read_json('evidence.json'))
        change(evidence)
        with patch.object(self.generator, 'read_json', side_effect=lambda name: evidence if name == 'evidence.json'
                          else json.loads(self.generator.read(name))):
            return self.generator.build('free')

    def test_a_changed_evidence_selector_fails_instead_of_publishing_paid_models(self):
        def rename(evidence):
            raw = json.dumps(evidence).replace('billing!~\\"free|promotion\\"', 'unexpected_selector')
            evidence.clear()
            evidence.update(json.loads(raw))
        with self.assertRaisesRegex(ValueError, 'selector'):
            self.with_evidence(rename)

    def test_an_unconverted_paid_selector_is_rejected(self):
        for selector in ('picker_eligible="true"', 'scope="t3"', 'orchestrator_model'):
            with self.subTest(selector=selector):
                def leak(evidence):
                    evidence['241']['unexpected_query'] = selector
                with self.assertRaisesRegex(ValueError, 'Paid selector remains'):
                    self.with_evidence(leak)

    def test_both_pages_share_one_panel_source_and_differ_only_by_scope(self):
        paid = json.loads(PAID.read_text())
        free = json.loads(PAGE.read_text())
        for pid in (260, 261, 262):
            paid_panel = next(p for p in paid['panels'] if p['id'] == pid)
            free_panel = next(p for p in free['panels'] if p['id'] == pid)
            self.assertEqual(paid_panel['options']['helpers'], free_panel['options']['helpers'])
            self.assertEqual(paid_panel['options']['styles'], free_panel['options']['styles'])
        # The paid page has one more panel: the orchestrator row, which the free page does not have.
        self.assertEqual([p['id'] for p in free['panels']], [p['id'] for p in paid['panels'] if p['id'] != 263])


if __name__ == '__main__':
    unittest.main()
