"""Picker-derived model panes and capacity cards follow the owner's design."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import model_selection
import snapshot
from metrics import MetricWriter

PAGE = ROOT / 'modules/self-hosted/siem/dashboards/ai-usage.json'


def helper(panel, name, rows, now=1767268800000):
    script = 'const helpers={};const context={handlebars:{registerHelper:(key,fn)=>helpers[key]=fn}};'
    script += "new Function('context'," + json.dumps(panel['options']['helpers']) + ')(context);'
    script += 'console.log(JSON.stringify(helpers[' + json.dumps(name) + '](' + json.dumps(rows) + ',' + str(now) + ')));'
    return json.loads(subprocess.check_output(['node', '-e', script], text=True))


def selection_rows(quality=80, left=.55, delta=-17, state='behind', custom=False):
    candidate = {'provider':'claude', 'model':'example-model', 'display_name':'Example Model',
        'available':True, 'quality_score':quality, 'quality_n':5, 'quality_s':4,
        'quality_basis':'AA + outcomes', 'capacity':{'remaining_ratio':left},
        'native':{'mapped':True,'provider_instance_id':'claudeAgent','model_id':'example-model',
                  'options':[{'id':'effort','values':['medium','high','max']}]},
        'pool':{'id':'claude:all','label':'All models','basis':'audit'},
        'access':{'billing':'subscription'}}
    value=model_selection.build({'generated_at':'2026-01-01T12:00:00Z','candidates':[candidate]},[])
    value['worker'][0]['limiting_window']={'kind':'weekly','quota_id':'seven_day','remaining_ratio':left,
        'pace_delta':delta,'pace_state':state,'reset_at':'2026-01-01T13:00:00Z',
        'reset_source':'custom' if custom else 'provider'}
    samples=model_selection.samples(value)
    return [{**labels,'field':name.removeprefix('ghostship_ai_picker_model_'),'value':number}
            for name,labels,number in samples]


class ProvidersPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page=json.loads(PAGE.read_text())
        cls.panels={p['id']:p for p in cls.page['panels']}

    def test_selection_precedes_capacity_and_has_only_current_categories(self):
        panels=self.page['panels']
        self.assertLess(next(i for i,p in enumerate(panels) if p['id']==231),
                        next(i for i,p in enumerate(panels) if p['id']==233))
        self.assertLess(next(i for i,p in enumerate(panels) if p['id']==233),
                        next(i for i,p in enumerate(panels) if p['id']==210))
        self.assertNotRegex(json.dumps(self.page), r'(?i)\b(3d|frontier|chief|delegate|bulk)\b')
        for panel_id, category in ((231,'orchestrator'),(233,'worker')):
            panel=self.panels[panel_id]
            self.assertEqual(panel['repeat'],category+'_model')
            self.assertEqual((panel['repeatDirection'],panel['maxPerRow'],panel['gridPos']['w']),('h',4,6))
            self.assertIn('category="'+category+'"',panel['targets'][0]['expr'])
            self.assertIn('picker_eligible="true"',panel['targets'][0]['expr'])

    def test_repeat_variables_use_published_order_and_freshness(self):
        variables={v['name']:v for v in self.page['templating']['list']}
        for category in ('orchestrator','worker'):
            query=variables[category+'_model']['query']['query']
            self.assertIn('sort(',query)
            self.assertIn('ghostship_ai_picker_model_position',query)
            self.assertIn('ghostship_ai_picker_model_selected',query)
            self.assertIn('ghostship_ai_collection_duration_seconds',query)
            self.assertEqual(variables[category+'_model']['sort'],0)
        query=variables['capacity_account']['query']['query']
        self.assertIn('scope="t3"',query)
        self.assertIn('account!="openrouter"',query)

    def test_repeated_model_regex_survives_query_string_parsing(self):
        # Grafana :regex emits one slash before punctuation. Quoted MetricsQL
        # strings consume escapes; raw literals must preserve the exact pattern.
        selected = r'ollama\|deepseek-v4\.1-flash:1017'
        for panel_id, category in ((231, 'orchestrator'), (233, 'worker')):
            query = self.panels[panel_id]['targets'][0]['expr']
            query = query.replace('${' + category + '_model:regex}', selected)
            for literal in re.findall(r'"selection_key",\s*(`[^`]*`|"[^"\n]*")', query):
                if literal == '"|"':
                    continue
                decoded = literal[1:-1] if literal.startswith('`') else json.loads(literal)
                self.assertEqual(decoded, selected)
                self.assertIsNotNone(re.fullmatch(decoded, 'ollama|deepseek-v4.1-flash:1017'))
                self.assertIsNone(re.fullmatch(decoded, 'ollama|deepseek-v4X1-flash:1017'))

    def test_capacity_freshness_timestamps_selectors_without_implicit_subqueries(self):
        query = next(v for v in self.page['templating']['list']
                     if v['name'] == 'capacity_account')['definition']
        # timestamp(composite-expression) is an implicit MetricsQL subquery;
        # Grafana's five-minute step moves it outside the ninety-second guard.
        self.assertNotRegex(query, r'timestamp\(\(')
        self.assertIn('timestamp(ghostship_ai_account_card_order{', query)

    def test_source_failures_and_stale_collection_are_visible_above_models(self):
        panel = self.panels[201]
        now = 1767268800000
        rows = [{'field':'collected','value':now / 1000},
                {'source':'t3_usage','field':'info','status':'error','reason':'timeout'},
                {'source':'opencode-go','field':'info','status':'error','reason':'http_forbidden'},
                {'source':'t3','field':'info','status':'ok'}]
        status = helper(panel, 'sourceHealth', rows, now)
        by_name = {row['name']:row for row in status}
        self.assertEqual(by_name['T3 usage']['text'], 'unavailable · timeout')
        self.assertEqual(by_name['OpenCode Go']['text'], 'unavailable · http_forbidden')
        self.assertEqual(by_name['T3 providers']['text'], 'current')
        self.assertTrue(all(row['state']=='error' for row in helper(panel,'sourceHealth',rows,now+601000)))
        self.assertEqual(helper(panel,'sourceHealth',[],now)[0]['text'],'missing collection timestamp')
        self.assertLess(self.page['panels'].index(panel), self.page['panels'].index(self.panels[231]))
        self.assertIn('Collector readings missing',panel['options']['defaultContent'])

    def test_text_only_model_details_come_from_real_canonical_samples(self):
        panel=self.panels[233]
        model=helper(panel,'selectionModels',selection_rows(custom=True))[0]
        self.assertEqual((model['quality'],model['rounds']),('80','4/5 accepted'))
        self.assertEqual(model['percent'],'55% left')
        self.assertEqual(model['paceText'],'▼ 17 behind')
        self.assertEqual(model['paceClass'],'behind')
        self.assertEqual(model['customReset'],'custom reset')
        self.assertEqual(model['resetText'],'resets in 1h 0m')
        self.assertEqual(model['effortText'],'high')
        self.assertTrue(model['defaultWorker'])
        self.assertEqual((model['providerPosition'],model['poolPosition']),(1,1))
        self.assertNotIn('class="bar"',panel['options']['content'])
        self.assertIn('data-field="remaining"',panel['options']['content'])
        self.assertIn('custom reset',panel['options']['content'])

    def test_selected_models_have_exactly_one_binding_graph_and_spent_models_remain_grey(self):
        panel=self.panels[233]
        self.assertEqual(panel['options']['content'].count('class="capacity-track"'),1)
        self.assertIn('.selection-card.restricted{opacity:.5}',panel['options']['styles'])
        model=helper(panel,'selectionModels',selection_rows(left=0,state='spent'))[0]
        self.assertEqual(model['fill'],0)
        self.assertTrue(model['restricted'])
        variables={v['name'] for v in self.page['templating']['list']}
        self.assertNotIn('free_model',variables)

    def test_healthy_capacity_is_neutral_and_pace_does_not_colour_the_bar(self):
        panel=self.panels[233]
        rows=selection_rows(left=.76,delta=-23,state='far_behind')
        for row in rows:
            row['reason']='every applicable window has headroom'
        model=helper(panel,'selectionModels',rows)[0]
        self.assertEqual(model['graphClass'],'')
        self.assertEqual(model['paceClass'],'far_behind')
        self.assertEqual(model['reasonClass'],'')
        self.assertEqual(model['reasonText'],'every applicable window has headroom')
        self.assertIn('.selection-card .reason{font-size:10.5px;margin-top:7px;color:#8b8f99',panel['options']['styles'])
        for row in rows:
            row['provider']='antigravity'
            row['reason']='the provider publishes no quota window for this account'
        model=helper(panel,'selectionModels',rows)[0]
        self.assertEqual(model['reasonText'],'Applicable reported quota has headroom')
        self.assertEqual(model['windowName'],'weekly')

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
        self.assertLess(self.page['panels'].index(self.panels[210]),self.page['panels'].index(panel))

    def test_quality_collapses_efforts_and_only_offers_comparison_when_observations_differ(self):
        import model_quality
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
            self.assertTrue(chosen['active'])
            self.assertEqual(chosen['compare'],different)
            self.assertFalse(next(model for model in models if model['model']=='spent')['active'])
            self.assertFalse(chosen['hasFindings'])
            self.assertFalse(chosen['hasQuota'])
        self.assertIn('data-quality-all',self.panels[250]['options']['content'])

    def test_pi_is_absent_from_dashboard_queries(self):
        for variable in self.page['templating']['list']:
            query=variable.get('definition','')
            if 'provider!=' in query:self.assertIn('provider!="pi"',query)
            if 'account!=' in query:self.assertIn('account!="pi"',query)
        for panel in self.page['panels']:
            for target in panel.get('targets',[]):
                query=target.get('expr','')
                if 'provider!=' in query:self.assertIn('provider!="pi"',query)
                if 'account!=' in query:self.assertIn('account!="pi"',query)

    def test_model_pace_reads_the_published_band_without_rounding_it_again(self):
        for state, delta, text in (('ahead',5.1,'▲ 5.1 ahead'),('on_pace',5,'● on pace'),
                                   ('behind',-5.1,'▼ 5.1 behind'),('behind',-20,'▼ 20 behind'),
                                   ('far_behind',-20.1,'▼ 20.1 behind')):
            with self.subTest(state=state,delta=delta):
                model=helper(self.panels[233],'selectionModels',selection_rows(delta=delta,state=state))[0]
                self.assertEqual((model['paceClass'],model['paceText']),(state,text))
        model=helper(self.panels[233],'selectionModels',selection_rows(left=0,state='spent'))[0]
        self.assertEqual(model['paceText'],'✕ spent')
        styles=self.panels[233]['options']['styles']
        self.assertIn('.selection-card .on_pace,.selection-card .unknown{color:#8b8f99}',styles)

    def test_cards_sort_by_published_position_and_keep_unknowns_honest(self):
        rows=[{'provider':'p','model':'a','category':'worker','display_name':'A','field':'position','value':2},
              {'provider':'p','model':'z','category':'worker','display_name':'Z','field':'position','value':1}]
        models=helper(self.panels[233],'selectionModels',rows)
        self.assertEqual([m['model'] for m in models],['z','a'])
        self.assertEqual(models[0]['quality'],'Unknown')
        self.assertEqual(models[0]['percent'],'No published limit')
        self.assertEqual(models[0]['rounds'],'rounds unknown')
        self.assertNotIn('NaN',json.dumps(models))

    def test_long_headers_allow_phone_wrapping_without_inner_scroll(self):
        # At 390px these headings need 66px of text; the old two-row panel
        # leaves only 50px and creates an internal scrollbar.
        for panel_id in (200, 234):
            self.assertGreaterEqual(self.panels[panel_id]['gridPos']['h'], 3)

    def test_only_one_evidence_drawer_and_no_inner_scroll(self):
        self.assertEqual(len([p for p in self.page['panels'] if p['type']=='row']),1)
        for panel in self.page['panels']:
            if panel['type']=='marcusolsson-dynamictext-panel':
                self.assertEqual(panel['options']['renderMode'],'allRows')
                self.assertIsInstance(panel['options']['externalStyles'],list)
                self.assertNotRegex(panel['options']['styles'],r'overflow(?:-y)?\s*:\s*(?:auto|scroll)')
        self.assertIn('Free workers',[link['title'] for link in self.page['links']])

    def test_public_model_identity_is_not_changed_by_metric_rendering(self):
        source={'provider':'example','model':'family/model','display_name':'Example',
            'available':True,'native':{'mapped':True,'provider_instance_id':'example','model_id':'family/model'},
            'capacity':{},'quality_score':80}
        value=model_selection.build({'candidates':[source]},[])
        writer=MetricWriter()
        for name,labels,number in model_selection.samples(value):writer.add(name,labels,number)
        self.assertIn('model="family/model"',writer.render())
        self.assertNotIn('model="family_model"',writer.render())


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
        self.assertIn('.capacity .sub.on_pace{color:#5b9bd5}',styles)

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
