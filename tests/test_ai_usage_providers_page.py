"""Providers page: tier rankings, then provider exhaustion, with unknown never drawn as a number."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import snapshot

PAGE = ROOT / 'modules/self-hosted/siem/dashboards/ai-usage.json'
NOW = 1767268800000
SECONDS = NOW / 1000


def call(panel, name, *args):
    script = 'const helpers={};const context={handlebars:{registerHelper:(key,fn)=>helpers[key]=fn}};'
    script += "new Function('context'," + json.dumps(panel['options']['helpers']) + ')(context);'
    script += 'console.log(JSON.stringify(helpers[' + json.dumps(name) + '](...' + json.dumps(list(args)) + ')));'
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def walk(panels):
    for panel in panels:
        yield panel
        yield from walk(panel.get('panels') or [])


def route(provider, model, position, category='worker', billing='subscription', state='available', left=None,
          pace=None, pace_state='unknown', window='weekly', overspent='false', reset=None, effort=''):
    labels = {'category': category, 'provider': provider, 'model': model, 'display_name': model, 'effort': effort,
              'state': state, 'billing': billing, 'overspent': overspent, 'pace_state': pace_state, 'window': window}
    rows = [{**labels, 'field': 'position', 'value': position}]
    for field, value in (('left', left), ('pace', pace), ('resetAt', reset)):
        if value is not None:
            rows.append({**labels, 'field': field, 'value': value})
    return rows


def window(account, kind, left, label=None, **extra):
    common = {'account': account, 'kind': kind, 'quota_id': extra.pop('quota_id', kind), 'label': label or kind.title(),
              'evidence': extra.pop('evidence', 'provider_reported'), 'not_used': extra.pop('not_used', '')}
    rows = [{**common, 'field': 'left', 'value': left}]
    state = extra.pop('state', None)
    if state:
        rows.append({**common, 'field': 'pace_state', 'state': state, 'value': 1})
    for field, value in extra.items():
        rows.append({**common, 'field': field, 'value': value})
    return rows


class PageShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}

    def test_identity_navigation_and_top_band_order(self):
        self.assertEqual((self.page['uid'], self.page['title']), ('ghostship-ai-usage', 'Providers'))
        self.assertEqual([link['url'] for link in self.page['links']],
                         ['/d/ghostship-ai-usage', '/d/ghostship-paid-models', '/d/ghostship-free-workers'])
        top = [p for p in self.page['panels'] if p['type'] != 'row']
        # The strip, the summary, the tier rankings, then provider exhaustion.
        self.assertEqual([p['id'] for p in top], [201, 260, 261, 262, 264, 265])
        # Two balanced columns: the lanes on the left, the provider lists on the right.
        by = {p['id']: p['gridPos'] for p in top}
        self.assertEqual((by[261]['x'], by[262]['x'], by[264]['x'], by[265]['x']), (0, 0, 12, 12))
        self.assertEqual(by[262]['y'], by[261]['y'] + by[261]['h'])
        self.assertEqual(by[265]['y'], by[264]['y'] + by[264]['h'])
        ordered = sorted(top, key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
        self.assertEqual([p['id'] for p in ordered], [201, 260, 261, 264, 262, 265])

    def test_no_table_sits_above_the_collapsed_evidence_row(self):
        rows = [p for p in self.page['panels'] if p['type'] == 'row']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['collapsed'])
        self.assertEqual({p['id'] for p in rows[0]['panels']}, {212, 202, 241, 243, 244})
        for panel in self.page['panels']:
            self.assertNotEqual(panel['type'], 'table', panel['id'])
        self.assertGreater(rows[0]['gridPos']['y'], max(p['gridPos']['y'] for p in self.page['panels'] if p['type'] != 'row'))

    def test_every_top_panel_is_one_full_dynamic_text_panel_without_inner_scroll(self):
        for panel in self.page['panels']:
            if panel['type'] != 'marcusolsson-dynamictext-panel':
                continue
            self.assertNotIn('repeat', panel)
            self.assertTrue(panel['transparent'])
            self.assertEqual(panel['options']['renderMode'], 'allRows')
            self.assertNotRegex(panel['options']['styles'], r'overflow(?:-y)?\s*:\s*(?:auto|scroll)')
            # A name is never cut short: it wraps.
            self.assertNotRegex(panel['options']['styles'], r'text-overflow\s*:\s*ellipsis')
            if panel['id'] != 201:
                self.assertIn('latest snapshot', panel['options']['defaultContent'])

    def test_panel_styles_are_scoped_so_they_cannot_restyle_grafana(self):
        for panel_id in (260, 261, 262, 264, 265):
            css = re.sub(r'@(?:media|container)[^{]*\{', '', self.panels[panel_id]['options']['styles'])
            for head in re.findall(r'(?:^|[}\n])\s*([^{}@]+)\{', css):
                for selector in head.split(','):
                    # The Business Text wrapper row is only styled where it holds this page's panel.
                    self.assertRegex(selector.strip(), r'^(?:\.gx|\.dt-row:has\(>\.gx\)|\.dt-row>\.gx)', selector)

    def test_queries_read_only_fresh_series_and_the_selected_route_of_each_provider(self):
        tolerance = '> scalar(max(timestamp(ghostship_ai_collection_duration_seconds))) - 90'
        for panel_id in (260, 261, 262, 264, 265):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn(tolerance, expr, panel_id)
            self.assertNotIn('== scalar(max(timestamp', expr, panel_id)
            self.assertNotIn('provider="pi"', expr)
            self.assertNotRegex(expr, r'timestamp\(\(')
        for panel_id in (261, 262):
            expr = self.panels[panel_id]['targets'][0]['expr']
            self.assertIn('ghostship_ai_picker_model_selected', expr)
            self.assertIn('on(category, provider, model, effort)', expr)
            for field in ('position', 'left', 'pace', 'resetAt'):
                self.assertIn('"field", "%s"' % field, expr)

    def test_free_lane_is_free_and_paid_lane_is_not(self):
        paid = self.panels[261]['targets'][0]['expr']
        free = self.panels[262]['targets'][0]['expr']
        self.assertIn('billing!~"free|promotion"', paid)
        self.assertNotIn('billing=~"free|promotion"', paid)
        self.assertIn('billing=~"free|promotion"', free)
        self.assertNotIn('opencode-go', json.dumps(self.panels[265]['targets']) + json.dumps(
            next(v for v in self.page['templating']['list'] if v['name'] == 'free_account')))

    def test_open_router_stays_out_of_paid_capacity_and_pi_out_of_every_query(self):
        self.assertIn('account!="openrouter"', self.panels[264]['targets'][0]['expr'])
        for panel in walk(self.page['panels']):
            for target in panel.get('targets', []):
                expr = target.get('expr', '')
                if 'provider!=' in expr:
                    self.assertIn('provider!="pi"', expr)
                if 'account!=' in expr:
                    self.assertIn('account!="pi"', expr)
        for variable in self.page['templating']['list']:
            self.assertIn('!="pi"', variable.get('definition', ''))

    def test_the_ordering_measure_is_named_paced_availability_where_it_is_drawn(self):
        for panel_id in (261, 262):
            self.assertIn('Paced Availability', self.panels[panel_id]['options']['content'], panel_id)
        self.assertIn('Paced Availability', self.panels[264]['options']['helpers'])

    def test_empty_announcements_are_labelled_without_inventing_reset_records(self):
        query = self.panels[202]['targets'][0]['expr']
        self.assertIn('absent(ghostship_ai_announced_reset_info)', query)
        self.assertIn('No reset announcement events yet', query)

    def test_t3_usage_stays_in_the_evidence_row_from_raw_buckets(self):
        table = self.panels[212]
        self.assertEqual([t['refId'] for t in table['targets']], ['A', 'B', 'C'])
        for target in table['targets']:
            self.assertIn('sum by (provider, model)', target['expr'])
            self.assertIn('$__from / 1000', target['expr'])

    def test_source_failures_and_stale_collection_are_visible_above_the_pools(self):
        panel = self.panels[201]
        rows = [{'field': 'collected', 'value': SECONDS},
                {'source': 't3_usage', 'field': 'info', 'status': 'error', 'reason': 'timeout'},
                {'source': 't3', 'field': 'info', 'status': 'ok'}]
        status = {row['name']: row for row in call(panel, 'sourceHealth', rows, NOW)}
        self.assertEqual(status['T3 usage']['text'], 'unavailable · timeout')
        self.assertEqual(status['T3 providers']['text'], 'current')
        self.assertTrue(all(row['state'] == 'error' for row in call(panel, 'sourceHealth', rows, NOW + 601000)))
        self.assertEqual(call(panel, 'sourceHealth', [], NOW)[0]['text'], 'missing collection timestamp')


class LaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = next(p for p in walk(json.loads(PAGE.read_text())['panels']) if p['id'] == 261)

    def lane(self, rows, lane='paid', limit=0):
        return call(self.panel, 'laneRows', rows, NOW, lane, limit)

    def test_rows_follow_the_picker_order_and_the_first_available_route_is_next(self):
        rows = (route('antigravity', 'a', 9, state='exhausted', left=0, pace_state='spent', window='quota')
                + route('claude', 'c', 11, state='reserved')
                + route('ollama', 'o', 5, left=.5, pace=-12.34, pace_state='behind')
                + route('codex', 'x', 7, left=.21, pace=-63.85, pace_state='far_behind', overspent='true'))
        lane = self.lane(rows)
        self.assertEqual([r['provider'] for r in lane['rows']], ['ollama', 'codex', 'antigravity', 'claude'])
        # The rank is the picker's own position, and only a route at position 1 is the next pick overall.
        self.assertEqual([r['first'] for r in lane['rows']], [True, False, False, False])
        self.assertEqual([r['next'] for r in lane['rows']], [False, False, False, False])
        self.assertEqual([r['rank'] for r in lane['rows']], [5, 7, 9, 11])
        by = {r['provider']: r for r in lane['rows']}
        self.assertEqual((by['ollama']['kind'], by['ollama']['word'], by['ollama']['paText']), ('warn', 'Behind pace', '−12.3'))
        self.assertEqual((by['codex']['kind'], by['codex']['word'], by['codex']['capacity']), ('bad', 'Overspent', '21% left'))
        self.assertEqual((by['antigravity']['kind'], by['antigravity']['word']), ('out', 'Out of quota'))
        self.assertEqual((by['claude']['kind'], by['claude']['word']), ('held', 'Held for review'))

    def test_an_out_or_held_route_is_never_the_next_pick(self):
        rows = route('a', 'm', 1, state='exhausted', left=0, pace_state='spent') + route('b', 'm', 2, state='reserved')
        self.assertFalse(any(r['next'] for r in self.lane(rows)['rows']))

    def test_unknown_capacity_never_reads_as_a_full_bar_or_a_number(self):
        inferred = self.lane(route('google', 'g', 8, billing='free', left=1, window='inferred', pace_state='on_pace'),
                             'free')['rows'][0]
        self.assertEqual((inferred['kind'], inferred['capacity'], inferred['leftText'], inferred['left']),
                         ('unk', 'no limit seen', '', None))
        self.assertFalse(inferred['paKnown'])
        silent = self.lane(route('claude', 'c', 1, category='orchestrator'), 'orchestrator')['rows'][0]
        self.assertEqual((silent['kind'], silent['capacity'], silent['leftText']), ('unk', 'capacity unknown · #465', ''))
        content = self.panel['options']['content']
        self.assertIn('{{#if pace}}', content)
        self.assertFalse(inferred['pace'])

    def test_only_a_long_window_is_paced_a_daily_window_shows_its_reset_alone(self):
        daily = self.lane(route('openrouter', 'm', 2, billing='free', left=1, window='daily', pace_state='on_pace',
                                reset=SECONDS + 3 * 3600), 'free')['rows'][0]
        self.assertEqual((daily['pace'], daily['paceLong'], daily['when']), (True, False, 'resets in 3h 0m'))
        weekly = self.lane(route('ollama', 'm', 1, left=.5, window='weekly', pace_state='behind', pace=-9))['rows'][0]
        self.assertEqual((weekly['pace'], weekly['paceLong'], weekly['paKnown']), (True, True, True))
        unknown = self.lane(route('codex', 'm', 1, left=.5, window='weekly'))['rows'][0]
        self.assertEqual((unknown['paceLong'], unknown['paKnown']), (True, False))

    def test_an_inferred_window_that_saw_a_limit_is_an_estimate_with_its_share(self):
        row = self.lane(route('nvidia', 'g', 3, billing='free', left=.4, window='inferred'), 'free')['rows'][0]
        self.assertEqual((row['leftText'], row['estimated'], row['capacity']), ('40%', True, '40% left'))

    def test_paced_availability_is_the_collector_number_and_missing_is_not_zero(self):
        rows = route('codex', 'x', 1, left=.5, pace=0, pace_state='on_pace') + route('ollama', 'y', 2, left=.5)
        by = {r['provider']: r for r in self.lane(rows)['rows']}
        self.assertTrue(by['codex']['paKnown'])
        self.assertEqual(by['codex']['paText'], '0')
        self.assertFalse(by['ollama']['paKnown'])
        self.assertEqual(by['ollama']['paText'], '')

    def test_the_free_lane_is_limited_and_reports_the_rest(self):
        rows = []
        for index in range(5):
            rows += route('p%d' % index, 'm', index + 1, billing='free', window='inferred', left=1)
        lane = self.lane(rows, 'free', 3)
        self.assertEqual((len(lane['rows']), lane['more'], lane['count']), (3, 2, 5))

    def test_lanes_split_by_category_and_billing(self):
        rows = (route('claude', 'o', 1, category='orchestrator') + route('codex', 'w', 2)
                + route('groq', 'f', 3, billing='free', window='inferred', left=1))
        self.assertEqual([r['provider'] for r in self.lane(rows, 'orchestrator')['rows']], ['claude'])
        self.assertEqual([r['provider'] for r in self.lane(rows, 'paid')['rows']], ['codex'])
        self.assertEqual([r['provider'] for r in self.lane(rows, 'free')['rows']], ['groq'])

    def test_the_reset_text_says_back_for_a_spent_route_and_resets_for_a_live_one(self):
        spent = self.lane(route('a', 'm', 1, state='exhausted', left=0, pace_state='spent', reset=SECONDS + 6 * 3600))['rows'][0]
        live = self.lane(route('b', 'm', 2, left=.5, reset=SECONDS + 90 * 60))['rows'][0]
        self.assertEqual((spent['when'], live['when']), ('back in 6h 0m', 'resets in 1h 30m'))


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}
        cls.paid = cls.panels[264]
        cls.free = cls.panels[265]

    def rows(self, rows, panel='paid', name='providerRows'):
        return call(self.paid if panel == 'paid' else self.free, name, rows, NOW)

    def test_the_lowest_known_window_leads_and_unused_windows_never_count(self):
        rows = (window('claude', 'session', .82, 'Session', resetAt=SECONDS + 5000)
                + window('claude', 'weekly', .51, 'Weekly', expected=.74, resetAt=SECONDS + 450000, state='behind', pace_delta=-23)
                + window('claude', 'weekly', .02, 'Weekly · Fable', not_used='true', quota_id='fable'))
        view = self.rows(rows)[0]
        self.assertEqual((view['head'], view['kind']), ('51% left', 'warn'))
        self.assertEqual(view['detail'], 'Weekly · ▼ −23 Paced Availability · back in 5.2d')
        self.assertEqual(view['bar'], {'width': 51, 'tick': 74, 'estimated': False})
        self.assertEqual([c['label'] for c in view['chips']], ['Session'])
        self.assertNotIn('Fable', json.dumps(view))

    def test_a_spent_window_is_out_of_quota_with_its_return(self):
        view = self.rows(window('grok', 'weekly', 0, 'Weekly', resetAt=SECONDS + 3600, state='spent'))[0]
        self.assertEqual((view['head'], view['kind'], view['detail']), ('Out of quota', 'out', 'Weekly · back in 1h 0m'))

    def test_overspent_is_far_behind_and_short_windows_never_carry_pace(self):
        far = self.rows(window('codex', 'weekly', .21, 'Weekly', expected=.85, state='far_behind', pace_delta=-63.8))[0]
        self.assertEqual(far['kind'], 'bad')
        for kind in ('session', 'daily', 'hourly', 'minute', 'inferred'):
            view = self.rows(window('x', kind, .4, kind.title(), expected=.9, state='behind', pace_delta=-50))[0]
            self.assertEqual(view['kind'], 'ok', kind)
            self.assertIsNone(view['bar']['tick'], kind)
            self.assertNotIn('Paced Availability', view['detail'], kind)

    def test_an_unreadable_provider_is_unknown_never_a_bar_or_a_zero(self):
        view = self.rows([{'account': 'claude', 'field': 'reported_missing', 'value': 1},
                          {'account': 'claude', 'field': 'availability', 'state': 'available', 'basis': 'learning', 'value': 1}])[0]
        self.assertEqual((view['head'], view['kind'], view['bar']), ('Unknown', 'unk', None))
        self.assertIn('could not be read', view['detail'])
        silent = self.rows([{'account': 'commandCode', 'field': 'availability', 'state': 'available',
                             'basis': 'published', 'value': 1}])[0]
        self.assertEqual((silent['head'], silent['kind'], silent['bar']), ('Unknown', 'unk', None))

    def test_an_inferred_window_with_no_limit_seen_is_unknown_not_one_hundred(self):
        view = self.rows(window('google', 'inferred', 1, 'Inferred · 1h', evidence='inferred'))[0]
        self.assertEqual((view['head'], view['kind'], view['bar']), ('Unknown', 'unk', None))

    def test_a_provider_with_known_and_unknown_windows_is_marked_partial(self):
        rows = (window('antigravity', 'quota', .5, 'Quota · Gemini', resetAt=SECONDS + 100)
                + window('antigravity', 'inferred', 1, 'Inferred', evidence='inferred'))
        view = self.rows(rows)[0]
        self.assertTrue(view['partial'])
        self.assertEqual([c['text'] for c in view['chips']], ['unknown'])

    def test_exhausted_providers_come_first_then_the_lowest_share_and_unknown_last(self):
        rows = (window('a', 'weekly', .6) + window('b', 'weekly', 0, state='spent') + window('c', 'weekly', .2)
                + [{'account': 'd', 'field': 'reported_missing', 'value': 1}])
        self.assertEqual([v['account'] for v in self.rows(rows)], ['b', 'c', 'a', 'd'])

    def test_only_a_confirmed_announced_reset_inside_a_week_is_shown(self):
        base = window('codex', 'weekly', .5, 'Weekly', expected=.5)

        def event(confidence, reset):
            return [{'account': 'codex', 'field': 'announced', 'confidence': confidence, 'reset_at': reset, 'value': 1}]
        shown = self.rows(base + event('confirmed', '2026-01-01T18:00:00Z'))[0]
        self.assertIn('⚡ reset confirmed in 6h 0m', shown['detail'])
        for rows in (base + event('low', '2026-01-01T18:00:00Z'), base + event('confirmed', 'time needs confirmation'),
                     base + event('confirmed', '2026-02-01T00:00:00Z')):
            self.assertNotIn('⚡', self.rows(rows)[0]['detail'])

    def test_a_blocked_free_provider_says_why_and_until_when(self):
        rows = [{'account': 'opencode', 'field': 'free_models', 'state': 'available', 'value': 0},
                {'account': 'opencode', 'field': 'free_models', 'state': 'unavailable', 'value': 46},
                {'account': 'opencode', 'field': 'free_reason', 'value': 44,
                 'reason': 'not offered by the T3 instance (deprecated in the catalog)'},
                {'account': 'opencode', 'field': 'free_reason', 'value': 1,
                 'reason': 'cooling down in the free pool until 2026-01-02T00:00:01Z'}]
        view = self.rows(rows, 'free', 'freeRows')[0]
        self.assertEqual((view['name'], view['head'], view['kind'], view['bar']), ('OpenCode Zen', 'Blocked', 'out', None))
        self.assertEqual(view['sub'], '44 not offered, 1 cooling until 2 Jan 00:00Z')

    def test_the_obsolete_label_wins_and_the_reason_text_is_the_fallback(self):
        rows = [{'account': 'opencode', 'field': 'free_models', 'state': 'available', 'value': 0},
                {'account': 'opencode', 'field': 'free_models', 'state': 'unavailable', 'value': 5},
                {'account': 'opencode', 'field': 'free_reason', 'value': 3, 'obsolete': 'true', 'reason': 'superseded by a newer family model'},
                {'account': 'opencode', 'field': 'free_reason', 'value': 2, 'obsolete': '', 'reason': 'not offered by the T3 instance'}]
        self.assertEqual(self.rows(rows, 'free', 'freeRows')[0]['sub'], '3 obsolete, 2 not offered')
        self.assertIn('count by (provider, reason, obsolete)', self.panels[265]['targets'][0]['expr'])

    def test_every_unknown_names_the_sub_issue_that_fills_it(self):
        claude = self.rows([{'account': 'claude', 'field': 'reported_missing', 'value': 1}])[0]
        self.assertTrue(claude['detail'].endswith('#465'))
        command = self.rows([{'account': 'commandCode', 'field': 'availability', 'state': 'available', 'basis': 'published', 'value': 1}])[0]
        self.assertTrue(command['detail'].endswith('#466'))
        antigravity = self.rows(window('antigravity', 'quota', 0, 'Quota · Gemini', resetAt=SECONDS + 100, state='spent'))[0]
        self.assertIn('no Paced Availability yet · #468', antigravity['detail'])
        self.assertIn('#467', self.panels[265]['options']['content'])
        self.assertIn('#467', self.panels[262]['options']['content'])
        silent = call(self.panels[261], 'laneRows', route('claude', 'c', 1, category='orchestrator'), NOW, 'orchestrator', 0)['rows'][0]
        self.assertEqual(silent['capacity'], 'capacity unknown · #465')

    def test_the_t3_strip_names_the_issue_that_ends_its_permanent_partial(self):
        rows = [{'field': 'collected', 'value': SECONDS}, {'source': 't3', 'field': 'info', 'status': 'partial', 'reason': 'unsupported'}]
        status = {r['name']: r for r in call(self.panels[201], 'sourceHealth', rows, NOW)}
        self.assertEqual(status['T3 providers']['text'], 'unavailable · unsupported · #470')

    def test_free_providers_without_a_limit_are_hatched_unknown_and_sorted_after_known_ones(self):
        rows = [{'account': 'groq', 'field': 'free_models', 'state': 'available', 'value': 3},
                {'account': 'groq', 'field': 'free_models', 'state': 'unavailable', 'value': 0},
                {'account': 'openrouter', 'field': 'free_models', 'state': 'available', 'value': 8},
                *window('openrouter', 'daily', .4, 'Daily', resetAt=SECONDS + 7200),
                *window('google', 'inferred', 1, 'Inferred', evidence='inferred'),
                {'account': 'google', 'field': 'free_models', 'state': 'available', 'value': 8}]
        views = self.rows(rows, 'free', 'freeRows')
        self.assertEqual([v['account'] for v in views], ['openrouter', 'google', 'groq'])
        self.assertEqual([v['head'] for v in views], ['40% left', 'No limit seen', 'No limit seen'])
        self.assertTrue(all(v['bar'] is None for v in views[1:]))
        self.assertEqual(views[0]['models'], '8 models · Daily · back in 2h 0m')

    def test_opencode_free_is_an_instance_not_a_provider(self):
        # Its routes are filed under the provider their model id names, and a bare id is an OpenCode Zen route.
        variables = {v['name']: v for v in self.page['templating']['list']}
        self.assertIn('account!="opencode-free"', variables['paid_account']['definition'])
        self.assertIn('account!="opencode-free"', variables['paid_account']['query']['query'])
        # The free provider list is the owner-approved providers; an OpenCode Free route counts for its own provider.
        free_variable = variables['free_account']['definition']
        self.assertIn('ghostship_ai_picker_model_approved_free', free_variable)
        self.assertIn('"provider", "$1", "model", "([^/]+)/.*"', free_variable)
        self.assertNotIn('account="opencode-free"', free_variable)
        self.assertIn('provider!="opencode-free"', self.panels[261]['targets'][0]['expr'])
        free = self.panels[262]['targets'][0]['expr']
        self.assertIn('"provider", "$1", "model", "([^/]+)/.*"', free)
        self.assertIn('"provider", "opencode", "model", "[^/]+"', free)

    def test_only_the_owner_approved_free_workers_are_listed(self):
        expr = self.panels[262]['targets'][0]['expr']
        selected = [part.split('}')[0] for part in expr.split('ghostship_ai_picker_model_selected{')[1:]]
        self.assertTrue(selected)
        for selector in selected:
            self.assertIn('approved_free="true"', selector)

    def test_an_account_window_that_reads_zero_makes_a_free_worker_out_of_quota(self):
        rows = route('nvidia', 'm', 3, billing='free', window='inferred', left=.9995) + [
            {'account': 'nvidia', 'quota_id': 'inferred:exhausted', 'evidence': 'inferred', 'field': 'acctLeft', 'value': 0},
            {'account': 'nvidia', 'quota_id': 'inferred:exhausted', 'evidence': 'inferred', 'field': 'acctReset', 'value': SECONDS + 3600}]
        row = call(self.panels[262], 'laneRows', rows, NOW, 'free', 0)['rows'][0]
        self.assertEqual((row['kind'], row['word'], row['capacity'], row['when']), ('out', 'Out of quota', '0% left', 'back in 1h 0m'))

    def test_a_provider_is_one_row_even_when_two_of_its_routes_are_selected(self):
        rows = (route('google', 'gemini-3.8-flash', 9, billing='free', window='inferred', left=.7)
                + route('google', 'google/gemini-3.8-flash', 10, billing='free', window='inferred', left=1))
        lane = call(self.panels[262], 'laneRows', rows, NOW, 'free', 0)['rows']
        self.assertEqual([(r['provider'], r['model'], r['rank']) for r in lane], [('google', 'gemini-3.8-flash', 9)])

    def test_only_the_first_orchestrator_is_listed(self):
        rows = route('claude', 'opus', 1, category='orchestrator') + route('codex', 'sol', 2, category='orchestrator')
        lane = call(self.panels[261], 'laneRows', rows, NOW, 'orchestrator', 0)['rows']
        self.assertEqual([r['provider'] for r in lane], ['claude'])

    def test_the_paid_list_never_lists_a_free_pool_provider(self):
        rows = window('codex', 'weekly', .5) + [{'account': 'groq', 'field': 'free_models', 'state': 'available', 'value': 3}]
        self.assertEqual([v['account'] for v in self.rows(rows)], ['codex'])

    def test_reported_windows_flow_through_the_real_emitter_without_short_pace(self):
        data = {'quota': {'accounts': {'claude': [
            {'kind': 'session', 'quota_id': 'five_hour', 'remaining_ratio': .1,
             'seconds_to_reset': 9000, 'duration_seconds': 18000, 'evidence': 'provider_reported'},
            {'kind': 'weekly', 'quota_id': 'seven_day', 'remaining_ratio': .55,
             'seconds_to_reset': 435456, 'duration_seconds': 604800, 'evidence': 'provider_reported'}]}}}
        fields = {'remaining_ratio': 'left', 'expected_remaining_ratio': 'expected', 'pace_state': 'pace_state',
                  'pace_delta_points': 'pace_delta', 'order': 'order'}
        rows = []
        for name, labels, value in snapshot.account_window_samples(data):
            key = name.removeprefix('ghostship_ai_account_window_')
            if key in fields:
                rows.append({**labels, 'field': fields[key], 'value': value})
        view = self.rows(rows)[0]
        self.assertEqual(view['head'], '10% left')
        self.assertIsNone(view['bar']['tick'])
        self.assertEqual([c['text'] for c in view['chips']], ['55%'])


class HeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = next(p for p in walk(json.loads(PAGE.read_text())['panels']) if p['id'] == 260)

    def test_next_picks_and_the_counts_of_out_overspent_and_unknown(self):
        rows = (route('claude', 'opus', 1, category='orchestrator')
                + route('ollama', 'o', 5, left=.5, pace=-12, pace_state='behind')
                + route('codex', 'x', 7, left=.2, pace=-60, pace_state='far_behind', overspent='true')
                + window('grok', 'weekly', 0, state='spent') + window('codex', 'weekly', .2, expected=.8, state='far_behind', pace_delta=-60)
                + window('ollama', 'weekly', .5, expected=.6, state='behind', pace_delta=-12)
                + [{'account': 'claude', 'field': 'reported_missing', 'value': 1},
                   {'account': 'opencode', 'field': 'free_models', 'state': 'available', 'value': 0},
                   {'account': 'opencode', 'field': 'free_models', 'state': 'unavailable', 'value': 9}])
        head = call(self.panel, 'headline', rows, NOW)
        self.assertEqual((head['orchestrator']['name'], head['orchestrator']['kind']), ('Claude', 'unk'))
        self.assertEqual(head['worker']['name'], 'Ollama')
        self.assertEqual((head['out']['count'], head['out']['text']), (2, 'Grok, OpenCode Zen'))
        # Overspent and behind pace are two counts: a provider that is only behind pace is not overspent.
        self.assertEqual((head['over']['count'], head['over']['text']), (1, 'Codex'))
        self.assertEqual((head['behind']['count'], head['behind']['text']), (1, 'Ollama'))
        self.assertEqual((head['unknown']['count'], head['unknown']['text']), (1, 'Claude'))

    def test_no_route_available_says_so_instead_of_naming_one(self):
        rows = route('a', 'm', 1, state='exhausted', left=0, pace_state='spent')
        head = call(self.panel, 'headline', rows, NOW)
        self.assertIsNone(head['worker'])
        self.assertIn('None available', self.panel['options']['content'])


if __name__ == '__main__':
    unittest.main()
