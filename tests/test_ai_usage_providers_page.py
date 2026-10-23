"""Providers page: two pools (Paid, Free) of compact cards with capacity, resets and T3 usage."""
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
DAY = 86400000


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


def window(account, kind, left, label=None, **extra):
    common = {'account': account, 'kind': kind, 'quota_id': kind, 'label': label or kind.title(),
              'evidence': 'provider_reported'}
    rows = [{**common, 'field': 'left', 'value': left}]
    for field, value in extra.items():
        rows.append({**common, 'field': field, 'value': value})
    return rows


class ProvidersPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}

    def test_page_identity_navigation_and_order(self):
        self.assertEqual((self.page['uid'], self.page['title']), ('ghostship-ai-usage', 'Providers'))
        self.assertEqual([link['title'] for link in self.page['links']], ['Providers', 'Paid models', 'Free models'])
        self.assertEqual([link['url'] for link in self.page['links']],
                         ['/d/ghostship-ai-usage', '/d/ghostship-paid-models', '/d/ghostship-free-workers'])
        self.assertEqual([p['id'] for p in self.page['panels']], [201, 210, 211, 240])
        # Models live on their own pages; the providers page has no model queries.
        self.assertNotIn('ghostship_ai_picker_model', json.dumps(self.page))

    def test_pools_are_single_panels_not_repeats_and_tables_are_collapsed(self):
        for panel_id, variable, scope in ((210, 'paid_account', 't3'), (211, 'free_account', 'free')):
            panel = self.panels[panel_id]
            self.assertNotIn('repeat', panel)
            self.assertEqual(panel['gridPos']['w'], 24)
            self.assertIn('${' + variable + ':regex}', panel['targets'][0]['expr'])
            query = next(v for v in self.page['templating']['list'] if v['name'] == variable)['query']['query']
            self.assertIn('scope="%s"' % scope, query)
            self.assertIn('grid-template-columns:1fr 1fr', panel['options']['styles'])
        rows = [p for p in self.page['panels'] if p['type'] == 'row']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['collapsed'])
        self.assertEqual({p['id'] for p in rows[0]['panels']}, {212, 202, 241, 243, 244})
        for panel in self.page['panels']:
            if panel['type'] == 'marcusolsson-dynamictext-panel':
                self.assertEqual(panel['options']['renderMode'], 'allRows')
                self.assertIsInstance(panel['options']['externalStyles'], list)
                self.assertNotRegex(panel['options']['styles'], r'overflow(?:-y)?\s*:\s*(?:auto|scroll)')

    def test_open_code_go_is_paid_and_never_on_the_free_pool(self):
        free = json.dumps(self.panels[211]['targets']) + json.dumps(
            next(v for v in self.page['templating']['list'] if v['name'] == 'free_account'))
        self.assertNotIn('opencode-go', free)
        card = call(self.panels[210], 'providerPool', window('opencode-go', 'monthly', .4), NOW)['cards'][0]
        self.assertEqual(card['name'], 'OpenCode Go')
        free_card = call(self.panels[211], 'providerPool', window('opencode', 'daily', 1), NOW)['cards'][0]
        self.assertEqual(free_card['name'], 'OpenCode Zen')

    def test_source_failures_and_stale_collection_are_visible_above_the_pools(self):
        panel = self.panels[201]
        rows = [{'field': 'collected', 'value': NOW / 1000},
                {'source': 't3_usage', 'field': 'info', 'status': 'error', 'reason': 'timeout'},
                {'source': 'opencode-go', 'field': 'info', 'status': 'error', 'reason': 'http_forbidden'},
                {'source': 't3', 'field': 'info', 'status': 'ok'}]
        status = helper(panel, 'sourceHealth', rows)
        by_name = {row['name']: row for row in status}
        self.assertEqual(by_name['T3 usage']['text'], 'unavailable · timeout')
        self.assertEqual(by_name['OpenCode Go']['text'], 'unavailable · http_forbidden')
        self.assertEqual(by_name['T3 providers']['text'], 'current')
        self.assertTrue(all(row['state'] == 'error' for row in helper(panel, 'sourceHealth', rows, NOW + 601000)))
        self.assertEqual(helper(panel, 'sourceHealth', [], NOW)[0]['text'], 'missing collection timestamp')
        self.assertIn('Collector readings missing', panel['options']['defaultContent'])
        self.assertTrue(panel['transparent'])

    def test_capacity_freshness_timestamps_selectors_without_implicit_subqueries(self):
        for name in ('paid_account', 'free_account'):
            query = next(v for v in self.page['templating']['list'] if v['name'] == name)['definition']
            self.assertNotRegex(query, r'timestamp\(\(')
            self.assertIn('timestamp(ghostship_ai_account_card_order{', query)

    def test_empty_announcements_are_labelled_without_inventing_reset_records(self):
        query = self.panels[202]['targets'][0]['expr']
        self.assertIn('absent(ghostship_ai_announced_reset_info)', query)
        self.assertIn('No reset announcement events yet', query)
        self.assertIn('max by (source_url, confidence, label, scope, reset_at)', query)
        self.assertNotIn('reset_at",', query.split('or label_replace', 1)[1])

    def test_pi_is_absent_from_dashboard_queries(self):
        for variable in self.page['templating']['list']:
            query = variable.get('definition', '')
            if 'account!=' in query:
                self.assertIn('account!="pi"', query)
        for panel in walk(self.page['panels']):
            for target in panel.get('targets', []):
                query = target.get('expr', '')
                if 'provider!=' in query:
                    self.assertIn('provider!="pi"', query)
                if 'account!=' in query:
                    self.assertIn('account!="pi"', query)

    def test_t3_usage_comes_from_the_raw_buckets_and_follows_the_time_range(self):
        for panel_id in (210, 211):
            query = self.panels[panel_id]['targets'][0]['expr']
            for metric in ('tokens', 'cost_usd', 'unpriced_records'):
                self.assertIn('ghostship_ai_t3_usage_bucket_' + metric, query)
            self.assertIn('$__from / 1000', query)
            self.assertIn('$__to / 1000', query)
        table = self.panels[212]
        self.assertEqual([t['refId'] for t in table['targets']], ['A', 'B', 'C'])
        for target in table['targets']:
            self.assertIn('sum by (provider, model)', target['expr'])
            self.assertIn('$__from / 1000', target['expr'])
        self.assertEqual(table['transformations'][0]['id'], 'merge')
        # Nothing on the page estimates a price: no local price table or multiplication.
        for panel_id in (210, 211):
            self.assertNotRegex(self.panels[panel_id]['options']['helpers'], r'(?i)per[_ ]?(million|mtok)|price\s*\*')


class ProviderPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(PAGE.read_text())
        cls.panels = {p['id']: p for p in walk(cls.page['panels'])}
        cls.paid = cls.panels[210]
        cls.free = cls.panels[211]

    def pool(self, rows, panel=None, now=NOW, start=None, end=None):
        return call(panel or self.paid, 'providerPool', rows, now, now - 7 * DAY if start is None else start,
                    now if end is None else end)

    def test_the_lowest_limit_leads_and_the_next_reset_is_the_soonest(self):
        rows = (window('claude', 'session', .82, 'Session', resetAt=NOW / 1000 + 5000)
                + window('claude', 'weekly', .51, 'Weekly', expected=.74, resetAt=NOW / 1000 + 450000)
                + [{'account': 'claude', 'kind': 'weekly', 'quota_id': 'weekly', 'label': 'Weekly',
                    'evidence': 'provider_reported', 'field': 'pace_state', 'state': 'behind', 'value': 1}])
        card = self.pool(rows)['cards'][0]
        self.assertEqual((card['head']['text'], card['head']['cls']), ('51%', 'behind'))
        self.assertEqual(card['next']['text'], 'resets in 1h 23m')
        self.assertEqual(card['next']['label'], 'Session')
        self.assertEqual([w['label'] for w in card['bars']], ['Session', 'Weekly'])
        self.assertTrue(card['bars'][1]['hasTick'])
        self.assertFalse(card['bars'][0]['hasTick'])
        self.assertEqual(card['overall']['width'], '51')

    def test_unused_limits_never_lower_the_headline_and_stay_grey_text(self):
        rows = (window('claude', 'weekly', .6, 'Weekly', expected=.5)
                + [{**r, 'quota_id': 'fable', 'label': 'Weekly · Fable', 'not_used': 'true'}
                   for r in window('claude', 'weekly', .05, 'Weekly · Fable')])
        card = self.pool(rows)['cards'][0]
        self.assertEqual(card['head']['text'], '60%')
        self.assertEqual([w['label'] for w in card['bars']], ['Weekly'])
        self.assertIn('Not used', card['unusedText'])
        self.assertIn('Fable', card['unusedText'])

    def test_a_spent_limit_is_red_zero_and_blocks_the_headline(self):
        card = self.pool(window('grok', 'weekly', 0, 'Weekly', resetAt=NOW / 1000 + 3600))['cards'][0]
        self.assertEqual((card['head']['text'], card['head']['cls']), ('0%', 'spent'))

    def test_only_confirmed_or_explicit_codex_resets_are_shown_on_the_card(self):
        base = window('codex', 'weekly', .5, 'Weekly')
        at = '2026-01-01T18:00:00Z'  # NOW + 6 hours
        event = lambda confidence, reset=at: {'account': 'codex', 'field': 'announced', 'confidence': confidence,
                                                'scope': 'codex', 'reset_at': reset, 'value': 1}
        card = self.pool(base + [event('confirmed')])['cards'][0]
        self.assertEqual(card['event']['text'], 'Reset confirmed · 1 Jan 18:00 UTC')
        self.assertEqual(card['event']['brief'], 'reset in 6h 0m')
        self.assertEqual(self.pool(base + [event('high')])['cards'][0]['event']['text'].split(' ·')[0], 'Reset announced')
        for rows in (base + [event('low')], base + [event('confirmed', 'time needs confirmation')],
                     base + [event('confirmed', '2026-02-01T00:00:00Z')]):
            self.assertIsNone(self.pool(rows)['cards'][0]['event'])
        other = self.pool(window('claude', 'weekly', .5) + [event('confirmed')])['cards'][0]
        self.assertIsNone(other['event'])

    def test_t3_tokens_and_cost_sum_the_days_inside_the_range_with_zero_filled_days(self):
        def bucket(day, tokens, cost=None, unpriced=0):
            common = {'account': 'codex', 'day': day, 'model': 'm'}
            rows = [{**common, 'field': 'usage_tokens', 'value': tokens}, {**common, 'field': 'usage_unpriced', 'value': unpriced}]
            if cost is not None:
                rows.append({**common, 'field': 'usage_cost', 'value': cost})
            return rows
        rows = (window('codex', 'weekly', .5) + bucket('2025-12-30', 1000000, 2.5) + bucket('2026-01-01', 3000000, 7.25)
                + bucket('2025-12-31', 500000, 1.0, unpriced=2))
        pool = self.pool(rows, start=Date_ms('2025-12-29'), end=NOW)
        usage = pool['cards'][0]['usage']
        self.assertEqual((usage['tokens'], usage['cost'], usage['partial']), ('4.5M', '$10.75', True))
        self.assertEqual(len(usage['bars']), 4)
        self.assertEqual(usage['bars'][0]['height'], 0)
        self.assertEqual(usage['bars'][3]['height'], 100)
        self.assertEqual((pool['tokens'], pool['cost']), ('4.5M', '$10.75'))
        unpriced = self.pool(window('codex', 'weekly', .5) + bucket('2026-01-01', 10, None), start=Date_ms('2025-12-29'))
        self.assertEqual(unpriced['cards'][0]['usage']['cost'], 'unpriced')
        none = self.pool(window('codex', 'weekly', .5) + bucket('2025-01-01', 10, 1))
        self.assertIsNone(none['cards'][0]['usage'])

    def test_free_provider_without_a_published_limit_is_one_calm_line(self):
        rows = [{'account': 'groq', 'field': 'availability', 'state': 'available', 'basis': 'unpublished', 'value': 1},
                {'provider': 'groq', 'state': 'available', 'field': 'free_models', 'value': 3}]
        card = self.pool(rows, self.free)['cards'][0]
        self.assertEqual((card['head']['text'], card['head']['cls']), ('No limit', 'open'))
        self.assertEqual(card['bars'], [])
        self.assertEqual(card['modelsBrief'], '3 models')
        self.assertEqual(card['models'], '3 models available')

    def test_free_provider_with_every_model_blocked_is_visibly_blocked(self):
        rows = window('opencode', 'inferred', 1, 'Inferred · 1m', rolling=1) + [
            {'provider': 'opencode', 'state': 'available', 'field': 'free_models', 'value': 0},
            {'provider': 'opencode', 'state': 'unavailable', 'field': 'free_models', 'value': 46}]
        card = self.pool(rows, self.free)['cards'][0]
        self.assertEqual((card['head']['text'], card['head']['cls']), ('Blocked', 'spent'))
        self.assertTrue(card['blocked'])
        self.assertIsNone(card['overall'])
        self.assertEqual(card['models'], '46 models blocked')

    def test_the_content_has_no_empty_first_card_and_names_every_pool(self):
        for panel, pool in ((self.paid, 'paid'), (self.free, 'free')):
            content = panel['options']['content']
            self.assertIn('data-pool="%s"' % pool, content)
            self.assertEqual(content.count('{{#each cards}}'), 1)
            self.assertIn('Unavailable', panel['options']['defaultContent'])
        self.assertIn('Paid providers', self.paid['options']['content'])
        self.assertIn('Free providers', self.free['options']['content'])


def Date_ms(day):
    import datetime
    return int(datetime.datetime.fromisoformat(day + 'T00:00:00+00:00').timestamp() * 1000)


class ProviderCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel=next(p for p in json.loads(PAGE.read_text())['panels'] if p['id']==210)

    def test_unused_windows_are_grey_even_when_spent_and_have_no_pace_tick(self):
        labels={'account':'antigravity','kind':'weekly','quota_id':'3p-weekly','label':'Weekly · Claude & GPT',
                'evidence':'provider_reported','not_used':'true'}
        rows=[{**labels,'field':'left','value':0},
              {**labels,'field':'expected','value':.5},
              {**labels,'field':'pace_state','state':'spent','value':1}]
        window=helper(self.panel,'capacityCards',rows)[0]['windows'][0]
        self.assertEqual(window['fillClass'],'not_used')
        self.assertEqual(window['paceClass'],'not_used')
        self.assertIn('Not used',window['sub'])
        self.assertFalse(window['hasTick'])
        self.assertTrue(window['notUsed'])
        self.assertIn('.fill.not_used',self.panel['options']['styles'])

    def card(self,kind='weekly',left=.55,state='behind',extra=()):
        common={'account':'claude','kind':kind,'quota_id':'synthetic','label':kind,'evidence':'provider_reported'}
        rows=[{**common,'field':'left','value':left},{**common,'field':'pace_state','state':state,'value':1},*extra]
        return helper(self.panel,'capacityCards',rows)[0]['windows'][0]

    def test_unused_limits_are_grey_with_real_usage_and_no_tick(self):
        common={'account':'claude','kind':'weekly','quota_id':'seven_day_fable',
                'label':'Weekly Fable','not_used':'true'}
        rows=[{**common,'field':'left','value':.25},
              {**common,'field':'expected','value':.8},
              {**common,'field':'resetAt','value':1767272400}]
        window=helper(self.panel,'capacityCards',rows)[0]['windows'][0]
        self.assertTrue(window['notUsed'])
        self.assertEqual(window['fillClass'],'not_used')
        self.assertEqual(window['paceClass'],'not_used')
        self.assertFalse(window['hasTick'])
        self.assertEqual(window['width'],'25')
        self.assertIn('Not used',window['sub'])
        self.assertIn('reset',window['sub'])
        self.assertIn('.fill.not_used',self.panel['options']['styles'])
        self.assertIn('not_used',self.panel['targets'][0]['expr'])

    def test_short_windows_never_have_pace_ticks_or_green_amber(self):
        for kind in ('session','hourly','daily','minute','inferred'):
            for state in ('ahead','behind','far_behind'):
                with self.subTest(kind=kind,state=state):
                    window=self.card(kind=kind,state=state)
                    self.assertEqual(window['fillClass'],'')
                    self.assertEqual(window['paceClass'],'')
                    self.assertFalse(window['hasTick'])
                    self.assertNotIn('pace',window['sub'])
                    self.assertNotIn('ahead',window['sub'])
                    self.assertNotIn('behind',window['sub'])
            self.assertEqual(self.card(kind=kind,left=0)['fillClass'],'spent')

    def test_long_window_pace_colour_is_text_only_and_capacity_stays_blue(self):
        for state,fill,symbol in (('ahead','ahead','▲'),('on_pace','','●'),('behind','behind','▼'),
                                  ('far_behind','spent','▼')):
            with self.subTest(state=state):
                window=self.card(state=state)
                self.assertEqual(window['fillClass'],'')
                self.assertEqual(window['paceClass'],state)
                self.assertIn(symbol,window['sub'])
        styles=self.panel['options']['styles']
        self.assertIn('.wm.on_pace{color:#5b9bd5}',styles)

    def test_no_limit_working_route_is_solid_blue_and_unavailable_is_grey(self):
        for state in ('available','unavailable'):
            card=helper(self.panel,'capacityCards',[{'account':'example','field':'availability',
                'state':state,'basis':'unpublished','reason':'not offered' if state=='unavailable' else '',
                'value':1}])[0]
            window=card['windows'][0]
            self.assertEqual(window['width'],'100')
            self.assertTrue(window['hasLeft'])
            self.assertEqual(window['fillClass'],'unavailable' if state=='unavailable' else '')
            if state=='available':self.assertEqual(window['label'],'no published limit')
            else:self.assertEqual(window['sub'],'not offered')
        self.assertNotIn('stripe',self.panel['options']['styles'])

    def test_missing_reported_read_never_becomes_learning_or_full_blue(self):
        available={'account':'claude','field':'availability','state':'available','basis':'learning','value':1}
        missing={'account':'claude','field':'reported_missing','value':1}
        for rows in ([available,missing],[missing,available]):
            window=helper(self.panel,'capacityCards',rows)[0]['windows'][0]
            self.assertEqual(window['label'],'Reported limits unavailable')
            self.assertEqual(window['fillClass'],'unavailable')
            self.assertIn('source read failed',window['sub'])

    def test_custom_reset_label_is_visible_and_minutes_carry_correctly(self):
        now=1767268800000
        common={'account':'codex','kind':'weekly','quota_id':'primary','label':'Weekly · custom reset','evidence':'provider_reported'}
        for seconds,wanted in ((3576,'1h 0m'),(68382,'19h 0m'),(-1,'resets now')):
            rows=[{**common,'field':'left','value':.5},{**common,'field':'resetAt','value':now/1000+seconds}]
            window=helper(self.panel,'capacityCards',rows,now)[0]['windows'][0]
            self.assertIn('custom reset',window['label'])
            self.assertIn(wanted,window['sub'])
            self.assertNotIn('60m',window['sub'])

    def test_reported_windows_flow_through_the_real_emitter_without_short_pace(self):
        data={'quota':{'accounts':{'claude':[
            {'kind':'session','quota_id':'five_hour','remaining_ratio':.1,
             'seconds_to_reset':9000,'duration_seconds':18000,'evidence':'provider_reported'},
            {'kind':'weekly','quota_id':'seven_day','remaining_ratio':.55,
             'seconds_to_reset':435456,'duration_seconds':604800,'evidence':'provider_reported'}]}}}
        fields={'remaining_ratio':'left','expected_remaining_ratio':'expected',
                'pace_state':'pace_state','pace_delta_points':'pace_delta','order':'order'}
        rows=[]
        for name,labels,value in snapshot.account_window_samples(data):
            key=name.removeprefix('ghostship_ai_account_window_')
            if key in fields:rows.append({**labels,'field':fields[key],'value':value})
        card=helper(self.panel,'capacityCards',rows)[0]
        session,weekly=card['windows']
        self.assertEqual(session['pct'],'10%')
        self.assertEqual(session['sub'],'')
        self.assertFalse(session['hasTick'])
        self.assertEqual(weekly['pct'],'55%')
        self.assertEqual(weekly['sub'],'▼ 17 behind')
        self.assertEqual(weekly['fillClass'],'')
        self.assertTrue(weekly['hasTick'])


if __name__ == "__main__":
    unittest.main()
