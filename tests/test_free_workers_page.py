"""Free models and workers dashboard mirrors the Providers and model decisions page."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import model_selection
import snapshot

PAGE = ROOT / 'modules/self-hosted/siem/dashboards/free-workers.json'


def helper(panel, name, rows, now=1767268800000):
    script = 'const helpers={};const context={handlebars:{registerHelper:(key,fn)=>helpers[key]=fn}};'
    script += "new Function('context'," + json.dumps(panel['options']['helpers']) + ')(context);'
    script += 'console.log(JSON.stringify(helpers[' + json.dumps(name) + '](' + json.dumps(rows) + ',' + str(now) + ')));'
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def free_selection_rows(quality=75, left=.60, delta=12, state='ahead', custom=False, available=True):
    candidate = {
        'provider': 'nvidia', 'model': 'deepseek-ai/deepseek-v4.1-flash', 'display_name': 'DeepSeek V4.1 Flash',
        'available': available, 'quality_score': quality, 'quality_n': 10, 'quality_s': 9,
        'quality_basis': 'AA + outcomes', 'capacity': {'remaining_ratio': left},
        'native': {'mapped': True, 'provider_instance_id': 'nvidia', 'model_id': 'deepseek-ai/deepseek-v4.1-flash',
                   'options': [{'id': 'effort', 'values': ['medium', 'high']}]},
        'pool': {'id': 'nvidia:default', 'label': 'Default', 'basis': 'audit'},
        'access': {'billing': 'free'}
    }
    value = model_selection.build({'generated_at': '2026-01-01T12:00:00Z', 'candidates': [candidate]}, [])
    value['worker'][0]['limiting_window'] = {
        'kind': 'weekly', 'quota_id': 'weekly', 'remaining_ratio': left,
        'pace_delta': delta, 'pace_state': state, 'reset_at': '2026-01-01T13:00:00Z',
        'reset_source': 'custom' if custom else 'provider'
    }
    samples = model_selection.samples(value)
    return [{**labels, 'field': name.removeprefix('ghostship_ai_picker_model_'), 'value': number}
            for name, labels, number in samples]


class FreeWorkersPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in cls.page['panels']}

    def test_page_metadata_and_fleet_navigation(self):
        self.assertEqual(self.page['uid'], 'ghostship-free-workers')
        self.assertEqual(self.page['timezone'], 'utc')
        self.assertFalse(self.page['editable'])
        titles = [link['title'] for link in self.page['links']]
        self.assertEqual(titles, ['Overview', 'Work', 'Providers', 'Host', 'Security', 'Pipeline'])

    def test_selection_precedes_capacity_and_has_free_pool_scope(self):
        panels = self.page['panels']
        self.assertLess(next(i for i, p in enumerate(panels) if p['id'] == 2231),
                        next(i for i, p in enumerate(panels) if p['id'] == 2210))
        panel = self.panels[2231]
        self.assertEqual(panel['repeat'], 'worker_model')
        self.assertEqual((panel['repeatDirection'], panel['maxPerRow'], panel['gridPos']['w']), ('h', 4, 6))
        self.assertIn('category="worker"', panel['targets'][0]['expr'])
        self.assertIn('billing=~"free|promotion"', panel['targets'][0]['expr'])

    def test_repeat_variables_use_free_scope_and_published_order(self):
        vars_by_name = {v['name']: v for v in self.page['templating']['list']}
        self.assertIn('provider', vars_by_name)
        self.assertIn('worker_model', vars_by_name)
        self.assertIn('capacity_account', vars_by_name)
        self.assertIn('scope="free"', vars_by_name['capacity_account']['query']['query'])
        self.assertIn('billing=~"free|promotion"', vars_by_name['worker_model']['query']['query'])

    def test_model_selection_card_renders_capacity_bar_and_public_policy(self):
        panel = self.panels[2231]
        rows = free_selection_rows(quality=85, left=0.72, delta=10, state='ahead')
        models = helper(panel, 'selectionModels', rows)
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model['display_name'], 'DeepSeek V4.1 Flash')
        self.assertEqual(model['providerName'], 'NVIDIA')
        self.assertEqual(model['percent'], '72% left')
        self.assertEqual(model['width'], 72)
        self.assertEqual(model['fillClass'], 'ahead')
        self.assertFalse(model['restricted'])
        self.assertIn('public only', panel['options']['content'])

    def test_exhausted_or_unavailable_models_are_marked_restricted(self):
        panel = self.panels[2231]
        spent_rows = free_selection_rows(left=0, state='spent', available=True)
        models = helper(panel, 'selectionModels', spent_rows)
        self.assertTrue(models[0]['restricted'])
        self.assertEqual(models[0]['statusText'], '✕ quota spent')
        self.assertEqual(models[0]['fillClass'], 'spent')

        unavail_rows = free_selection_rows(left=0.5, state='on_pace', available=False)
        models = helper(panel, 'selectionModels', unavail_rows)
        self.assertTrue(models[0]['restricted'])

    def test_cards_sort_by_published_position_and_keep_unknowns_honest(self):
        rows = [{'provider': 'nvidia', 'model': 'a', 'category': 'worker', 'display_name': 'A', 'field': 'position', 'value': 2},
                {'provider': 'nvidia', 'model': 'z', 'category': 'worker', 'display_name': 'Z', 'field': 'position', 'value': 1}]
        models = helper(self.panels[2231], 'selectionModels', rows)
        self.assertEqual([m['model'] for m in models], ['z', 'a'])
        self.assertEqual(models[0]['quality'], 'Unknown')
        self.assertEqual(models[0]['percent'], 'No long-window reading')
        self.assertEqual(models[0]['rounds'], 'rounds unknown')
        self.assertNotIn('NaN', json.dumps(models))

    def test_only_one_evidence_drawer_and_no_inner_scroll(self):
        self.assertEqual(len([p for p in self.page['panels'] if p['type'] == 'row']), 1)
        for panel in self.page['panels']:
            if panel['type'] == 'marcusolsson-dynamictext-panel':
                self.assertEqual(panel['options']['renderMode'], 'allRows')
                self.assertIsInstance(panel['options']['externalStyles'], list)
                self.assertNotRegex(panel['options']['styles'], r'overflow(?:-y)?\s*:\s*(?:auto|scroll)')


class FreeProviderCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = next(p for p in json.loads(PAGE.read_text())['panels'] if p['id'] == 2210)

    def card(self, account='nvidia', kind='daily', left=.65, state='behind', extra=()):
        common = {'account': account, 'kind': kind, 'quota_id': 'daily', 'label': kind, 'evidence': 'provider_reported'}
        rows = [{**common, 'field': 'left', 'value': left}, {**common, 'field': 'pace_state', 'state': state, 'value': 1}, *extra]
        return helper(self.panel, 'capacityCards', rows)[0]['windows'][0]

    def test_short_windows_never_have_pace_ticks_or_green_amber(self):
        for kind in ('session', 'hourly', 'daily', 'minute', 'inferred'):
            for state in ('ahead', 'behind', 'far_behind'):
                with self.subTest(kind=kind, state=state):
                    window = self.card(kind=kind, state=state)
                    self.assertEqual(window['fillClass'], '')
                    self.assertEqual(window['paceClass'], '')
                    self.assertFalse(window['hasTick'])
                    self.assertNotIn('pace', window['sub'])
                    self.assertNotIn('ahead', window['sub'])
                    self.assertNotIn('behind', window['sub'])
            self.assertEqual(self.card(kind=kind, left=0)['fillClass'], 'spent')

    def test_long_window_text_and_fill_take_the_same_owner_colour(self):
        for state, fill, symbol in (('ahead', 'ahead', '▲'), ('on_pace', '', '●'), ('behind', 'behind', '▼'),
                                  ('far_behind', 'spent', '▼')):
            with self.subTest(state=state):
                window = self.card(kind='weekly', state=state)
                self.assertEqual(window['fillClass'], fill)
                self.assertEqual(window['paceClass'], state)
                self.assertIn(symbol, window['sub'])


if __name__ == '__main__':
    unittest.main()
