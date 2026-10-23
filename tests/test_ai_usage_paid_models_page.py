"""Paid models page: the picker selections and the quality ranking follow the owner's design."""
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

PAGE = ROOT / 'modules/self-hosted/siem/dashboards/paid-models.json'


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
    value=model_selection.build({'generated_at':'2026-01-01T12:00:00Z','candidates':[candidate],
        'quota': {'accounts': {'claude': [{'kind': 'weekly', 'remaining_ratio': .9,
            'check_at': '2026-01-01T12:00:00Z', 'reset_at': '2026-01-02T12:00:00Z',
            'duration_seconds': 604800}]}}}, [], evidence={'policy': {'model_selection': {
                'worker_pool_guards': {'claude': {'kind': 'weekly', 'minimum_remaining_ratio': .2,
                                                'require_pace_headroom': True}}}}})
    value['worker'][0]['limiting_window']={'kind':'weekly','quota_id':'seven_day','remaining_ratio':left,
        'pace_delta':delta,'pace_state':state,'reset_at':'2026-01-01T13:00:00Z',
        'reset_source':'custom' if custom else 'provider'}
    samples=model_selection.samples(value)
    return [{**labels,'field':name.removeprefix('ghostship_ai_picker_model_'),'value':number}
            for name,labels,number in samples]


class PaidModelsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page=json.loads(PAGE.read_text())
        cls.panels={}
        def walk(panels):
            for p in panels:
                cls.panels[p['id']]=p
                walk(p.get('panels') or [])
        walk(cls.page['panels'])

    def test_page_identity_navigation_and_layout(self):
        self.assertEqual((self.page['uid'],self.page['title']),('ghostship-paid-models','Paid models'))
        self.assertEqual([link['title'] for link in self.page['links']],['Providers','Paid models','Free models'])
        order=[p['id'] for p in self.page['panels']]
        self.assertEqual(order,[201,231,233,250,240])
        self.assertLess(order.index(231),order.index(250))
        self.assertNotRegex(json.dumps(self.page), r'(?i)\b(3d|frontier|chief|delegate|bulk)\b')
        self.assertEqual({v['name'] for v in self.page['templating']['list']},{'provider','orchestrator_model','worker_model'})

    def test_selection_lanes_are_single_panels_not_repeats(self):
        # A repeat leaves an empty first card and one tall card per row; a single
        # panel lays the cards out as a dense grid (two per row on a phone).
        for panel_id, category, width in ((231,'orchestrator',7),(233,'worker',17)):
            panel=self.panels[panel_id]
            self.assertNotIn('repeat',panel)
            self.assertEqual(panel['gridPos']['w'],width)
            self.assertIn('category="'+category+'"',panel['targets'][0]['expr'])
            self.assertIn('picker_eligible="true"',panel['targets'][0]['expr'])
            self.assertIn('${'+category+'_model:regex}',panel['targets'][0]['expr'])
            self.assertIn('grid-template-columns:1fr 1fr',panel['options']['styles'])

    def test_lane_cards_are_ranked_in_lane_order_and_name_paced_availability(self):
        panel=self.panels[233]
        rows=[]
        for model,position,left,delta,state in (('a',7,.5,-12.34,'behind'),('b',3,None,None,None),('c',9,0,-50,'spent')):
            labels={'provider':'codex','model':model,'category':'worker','display_name':model.upper(),
                    'state':'available' if model!='c' else 'exhausted','window':'weekly','pace_state':state or ''}
            rows.append({**labels,'field':'position','value':position})
            if left is not None:rows.append({**labels,'field':'remaining_ratio','value':left})
            if delta is not None:rows.append({**labels,'field':'pace_delta','value':delta})
        models=helper(panel,'selectionModels',rows)
        self.assertEqual([m['model'] for m in models],['b','a','c'])
        self.assertEqual([m['rank'] for m in models],[1,2,3])
        self.assertEqual([m['next'] for m in models],[True,False,False])
        self.assertEqual(models[1]['paText'],'Paced Availability −12.3')
        self.assertEqual(models[2]['paText'],'✕ spent')
        self.assertTrue(models[0]['noLimit'])
        self.assertFalse(models[1]['noLimit'])
        content=panel['options']['content']
        self.assertIn('{{#unless this.noLimit}}<div class="capacity-track"',content)
        self.assertEqual(content.count('class="capacity-track"'),1)
        self.assertIn('next pick',content)

    def test_free_provider_names_are_human_on_the_model_cards(self):
        row={'provider':'cloudflare-workers-ai','model':'m','category':'worker','field':'position','value':1}
        self.assertEqual(helper(self.panels[233],'selectionModels',[row])[0]['providerName'],'Cloudflare')
        row['provider']='opencode'
        self.assertEqual(helper(self.panels[233],'selectionModels',[row])[0]['providerName'],'OpenCode Zen')

    def test_every_dashboard_panel_has_room_for_its_content(self):
        for panel in self.page['panels']:
            if panel['type']=='row':
                self.assertTrue(panel['collapsed'])
                continue
            self.assertLessEqual(panel['gridPos']['x']+panel['gridPos']['w'],24)


    def test_repeat_variables_use_published_order_and_freshness(self):
        variables={v['name']:v for v in self.page['templating']['list']}
        for category in ('orchestrator','worker'):
            query=variables[category+'_model']['query']['query']
            self.assertIn('sort(',query)
            self.assertIn('ghostship_ai_picker_model_position',query)
            self.assertIn('ghostship_ai_picker_model_selected',query)
            self.assertIn('ghostship_ai_collection_duration_seconds',query)
            self.assertEqual(variables[category+'_model']['sort'],0)
        self.assertIn('provider!="openrouter"',variables['provider']['definition'])

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
        self.assertIn('.selection-card .reason{font-size:10.5px;margin-top:4px;color:#8b8f99',panel['options']['styles'])
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
        self.assertLess(self.page['panels'].index(self.panels[233]),self.page['panels'].index(panel))

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
            self.assertTrue(chosen['active'])
            self.assertEqual(chosen['compare'],different)
            self.assertFalse(next(model for model in models if model['model']=='spent')['active'])
            self.assertFalse(chosen['hasFindings'])
            self.assertFalse(chosen['hasQuota'])
        self.assertIn('data-quality-controls',self.panels[250]['options']['content'])

    def test_quality_hook_builds_controls_after_grafana_sanitization(self):
        subprocess.run(['node',str(ROOT/'tests/fixtures/ai-usage/quality-hook-dom.cjs'),str(PAGE)],check=True)
        self.assertNotIn('<input',self.panels[250]['options']['content'])

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
