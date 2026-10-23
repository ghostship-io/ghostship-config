"""Free models dashboard is generated from Paid models: one selected model per free provider."""
import json
import copy
import importlib.util
import tempfile
from unittest.mock import patch
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import model_selection
import snapshot

PAGE = ROOT / 'modules/self-hosted/siem/dashboards/free-workers.json'
PROVIDERS = ROOT / 'modules/self-hosted/siem/dashboards/ai-usage.json'


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

    def test_committed_dashboard_matches_generator(self):
        cmd = [sys.executable, str(ROOT / 'scripts/generate-free-workers-dashboard.py'), '--check']
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"free-workers.json differs from generator:\n{res.stderr}")

    def test_page_metadata_and_fleet_navigation(self):
        self.assertEqual(self.page['uid'], 'ghostship-free-workers')
        self.assertEqual(self.page['timezone'], 'utc')
        self.assertFalse(self.page['editable'])
        titles = [link['title'] for link in self.page['links']]
        self.assertEqual(titles, ['Providers', 'Paid models', 'Free models'])

    def test_one_full_width_free_lane_with_free_pool_scope(self):
        self.assertEqual([p['id'] for p in self.page['panels']], [201, 233, 250, 240])
        panel = self.panels[233]
        self.assertNotIn('repeat', panel)
        self.assertEqual((panel['gridPos']['x'], panel['gridPos']['w']), (0, 24))
        self.assertIn('category="worker"', panel['targets'][0]['expr'])
        self.assertIn('billing=~"free|promotion"', panel['targets'][0]['expr'])
        queries = json.dumps([t for p in self.page['panels'] if p['id'] in (233, 250) for t in p['targets']]
                             + self.page['templating']['list'])
        self.assertNotIn('opencode-go', queries)
        self.assertNotIn('subscription', queries)
        self.assertIn('data-lane="free"', panel['options']['content'])
        self.assertIn('one selected model per free provider', panel['options']['content'])

    def test_repeat_variables_use_free_scope_and_published_order(self):
        vars_by_name = {v['name']: v for v in self.page['templating']['list']}
        self.assertIn('provider', vars_by_name)
        self.assertIn('worker_model', vars_by_name)
        self.assertNotIn('orchestrator_model', vars_by_name)
        self.assertIn('billing=~"free|promotion"', vars_by_name['worker_model']['query']['query'])
        self.assertIn('ghostship_ai_picker_model_selected', vars_by_name['worker_model']['query']['query'])

    def test_a_free_provider_with_no_available_model_stays_visible_and_grey(self):
        panel = self.panels[233]
        self.assertIn('ghostship_ai_provider_free_models{state="unavailable"', panel['targets'][0]['expr'])
        self.assertIn('unless on(provider)', panel['targets'][0]['expr'])
        rows = [{'provider': 'opencode', 'field': 'free_blocked', 'value': 46, 'category': 'worker'},
                {'provider': 'cohere', 'field': 'free_blocked', 'value': 0, 'category': 'worker'}]
        blocked = helper(panel, 'freeBlocked', rows)
        self.assertEqual(blocked, [{'provider': 'opencode', 'count': 46, 'name': 'OpenCode Zen', 'icon': 'O'}])
        self.assertIn('{{#each (freeBlocked data)}}', panel['options']['content'])
        self.assertIn('No model available', panel['options']['content'])
        self.assertIn('restricted blocked', panel['options']['content'])

    def test_model_selection_card_renders_capacity_bar_and_public_policy(self):
        panel = self.panels[233]
        rows = free_selection_rows(quality=85, left=0.72, delta=10, state='ahead')
        models = helper(panel, 'selectionModels', rows)
        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model['display_name'], 'DeepSeek V4.1 Flash')
        self.assertEqual(model['providerName'], 'NVIDIA')
        self.assertEqual(model['percent'], '72% left')
        self.assertEqual(model['paceClass'], 'ahead')
        self.assertFalse(model['restricted'])

    def test_exhausted_or_unavailable_models_are_marked_restricted(self):
        panel = self.panels[233]
        spent_rows = free_selection_rows(left=0, state='spent', available=True)
        models = helper(panel, 'selectionModels', spent_rows)
        self.assertTrue(models[0]['restricted'])
        self.assertEqual(models[0]['paceText'], '✕ spent')
        self.assertEqual(models[0]['paceClass'], 'spent')

        unavail_rows = free_selection_rows(left=0.5, state='on_pace', available=False)
        models = helper(panel, 'selectionModels', unavail_rows)
        self.assertTrue(models[0]['restricted'])

    def test_cards_sort_by_published_position_and_keep_unknowns_honest(self):
        rows = [{'provider': 'nvidia', 'model': 'a', 'category': 'worker', 'display_name': 'A', 'field': 'position', 'value': 2},
                {'provider': 'nvidia', 'model': 'z', 'category': 'worker', 'display_name': 'Z', 'field': 'position', 'value': 1}]
        models = helper(self.panels[233], 'selectionModels', rows)
        self.assertEqual([m['model'] for m in models], ['z', 'a'])
        self.assertEqual(models[0]['quality'], 'Unknown')
        self.assertEqual(models[0]['percent'], 'No published limit')
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
        cls.panel = next(p for p in json.loads(PROVIDERS.read_text())['panels'] if p['id'] == 210)

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

    def test_long_window_pace_is_text_only_like_providers(self):
        for state, symbol in (('ahead', '▲'), ('on_pace', '●'), ('behind', '▼'),
                              ('far_behind', '▼')):
            with self.subTest(state=state):
                window = self.card(kind='weekly', state=state)
                self.assertEqual(window['fillClass'], '')
                self.assertEqual(window['paceClass'], state)
                self.assertIn(symbol, window['sub'])


class FreeDashboardGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('free_dashboard', ROOT / 'scripts/generate-free-workers-dashboard.py')
        cls.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.generator)
        cls.source = json.loads(cls.generator.SRC.read_text())

    def generate(self, source):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'source.json'
            source_path.write_text(json.dumps(source))
            with patch.object(self.generator, 'SRC', source_path):
                return json.loads(self.generator.generate())

    def test_changed_source_selectors_fail_instead_of_publishing_paid_models(self):
        # Each transformation must find its expected source contract.
        for old in ('picker_eligible="true",provider!="openrouter"',
                    'picker_eligible="true",provider=~"$provider",provider!="openrouter"'):
            with self.subTest(selector=old):
                raw = json.dumps(self.source)
                changed = raw.replace(json.dumps(old)[1:-1], 'unexpected_selector')
                self.assertNotEqual(changed, raw)
                with self.assertRaisesRegex(ValueError, 'selector'):
                    self.generate(json.loads(changed))

    def test_unconverted_paid_selector_is_rejected(self):
        for selector in ('picker_eligible="true"', 'scope="t3"', 'orchestrator_model'):
            with self.subTest(selector=selector):
                source = copy.deepcopy(self.source)
                source['panels'][0]['unexpected_query'] = selector
                with self.assertRaisesRegex(ValueError, 'Paid selector remains'):
                    self.generate(source)

    def test_generated_lane_replaces_the_orchestrator_lane_and_keeps_stable_ids(self):
        page = self.generate(copy.deepcopy(self.source))
        self.assertEqual([p['id'] for p in page['panels']], [201, 233, 250, 240])
        self.assertEqual(page['panels'][1]['gridPos']['w'], 24)
        evidence = next(p for p in page['panels'] if p['type'] == 'row')
        self.assertEqual([p['id'] for p in evidence['panels']], [241, 242])
        self.assertTrue(all(p['gridPos']['y'] > evidence['gridPos']['y'] for p in evidence['panels']))

    def test_changed_lane_markup_fails_instead_of_dropping_blocked_providers(self):
        source = copy.deepcopy(self.source)
        panel = next(p for p in source['panels'] if p['id'] == 233)
        panel['options']['content'] = panel['options']['content'].replace('</div></section>', '</div>')
        with self.assertRaisesRegex(ValueError, 'blocked free providers'):
            self.generate(source)
