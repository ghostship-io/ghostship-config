"""Measured quality must change real choices without alias or effort leakage."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import model_quality as quality
import model_selection as selection
import main
from types import ModuleType
from unittest.mock import Mock

NOW = 1800000000


def candidate(model='model', aa=80):
    return {'provider':'example', 'model':model, 'display_name':model, 'available':True,
            'capacity':{'remaining_ratio':1}, 'aa':{'state':'measured',
                'indices':{'intelligence':aa}, 'fetched_at':'2026-10-23T00:00:00Z'},
            'native':{'mapped':True, 'provider_instance_id':'native', 'model_id':model,
                      'options':[{'id':'effort', 'values':['low','high']}]}}


def rounds(model='model', effort='low', n=5, passed=True):
    return [{'schema_version':1, 'source':'bench', 'id':str(i)+model+effort,
             'provider':'native', 'model':model, 'effort':'low' if effort is None else effort,
             'effort_option':'effort', 'passed':passed, 'merged':None,
             'date':NOW-i, 'wall_seconds':60, 'tokens':100} for i in range(n)]


class QualityTests(unittest.TestCase):
    def test_shared_reader_supplies_dated_evidence_and_failure_is_explicit(self):
        parent=ModuleType('ghostship_t3');parent.__path__=[]
        module=ModuleType('ghostship_t3.models')
        module.read_evidence=Mock(return_value=rounds())
        with patch.dict(sys.modules,{'ghostship_t3':parent,'ghostship_t3.models':module}):
            rows,state=quality.read_evidence(NOW)
            self.assertEqual((len(rows),state),(5,'ok'))
            module.read_evidence.assert_called_once_with(now=NOW)
            module.read_evidence.side_effect=OSError('unreadable')
            self.assertEqual(quality.read_evidence(NOW),([],'unreadable'))

    def test_dated_last_public_prior_stays_visible_without_claiming_freshness(self):
        row=candidate(aa=None)
        cache={'status':'stale','index_version':'4.3','fetched_at':'2026-10-21T00:00:00Z',
               'records':[{'slug':'model','model':'Model','name':'Model',
                           'indices':{'intelligence_index':71},'cost_per_task':1}]}
        result=quality.build([row],[],NOW,prior_cache=cache)
        self.assertEqual(result['rows'][0]['aa'],71)
        self.assertEqual(result['rows'][0]['aa_state'],'stale')
        self.assertEqual(result['rows'][0]['aa_date'],cache['fetched_at'])
        result=quality.build([candidate(aa=None)],[],NOW,prior_cache={**cache,'index_version':'other'})
        self.assertIsNone(result['rows'][0]['overall'])

    def test_last_prior_reader_does_not_relabel_an_old_fetch_as_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'aa.json'
            path.write_text(json.dumps({'intelligence_index_version':'4.3',
                'fetched_at_epoch':NOW-2*86400,'fetched_at':'2026-10-21T00:00:00Z',
                'records':[{'slug':'model'}]}))
            self.assertEqual(quality.aa_module.load_cache(path,NOW)['records'],[])
            prior=quality.aa_module.load_cache(path,NOW,allow_stale=True)
            self.assertEqual(prior['status'],'stale')
            self.assertEqual(prior['records'],[{'slug':'model'}])
            self.assertEqual(prior['age_seconds'],2*86400)

    def test_worker_price_ceiling_never_promotes_a_costlier_model(self):
        reference={'provider':'codex','model':'gpt-6.1-sol','price':{'input':2,'output':8,'cache_read':.2}}
        self.assertTrue(selection.worker_cost_allowed(reference,[reference]))
        self.assertFalse(selection.worker_cost_allowed({'price':{'input':1,'output':9}},[reference]))
        self.assertFalse(selection.worker_cost_allowed({'price':{'input':1,'output':2,'cache_read':.3}},[reference]))
        self.assertFalse(selection.worker_cost_allowed({'price':{}},[reference]))
        self.assertTrue(selection.worker_cost_allowed({'access':{'billing':'free'}},[]))

    def test_collector_entrypoint_publishes_observed_choice_and_metrics(self):
        reference=candidate('gpt-6.1-sol',aa=90)
        reference['provider']='codex'
        reference['price']={'input':2,'output':8}
        measured=candidate('measured',aa=70)
        measured['price']={'input':1,'output':3}
        base={'generated_at':'2027-01-15T08:00:00Z','candidates':[reference,measured]}
        with patch.object(main.snapshot_module,'build_snapshot',return_value=base):
            result=main.build_snapshot([],[],{},NOW,model_evidence=rounds('measured',n=30),
                                       model_evidence_state='ok')
        self.assertEqual(result['model_selection']['default_worker']['model'],'measured')
        row=result['model_selection']['worker'][0]
        overall=next(r['overall'] for r in result['model_quality']['rows']
                     if r['model']=='measured' and r['effort']=='low')
        self.assertEqual(row['quality_score'],overall)
        self.assertNotIn('quality_evidence',result['candidates'][0])
        text=main.render([],[],NOW,0,result)
        self.assertIn('ghostship_ai_quality_overall',text)
        self.assertIn('ghostship_ai_picker_model_selected',text)

    def test_prior_then_smooth_verified_takeover(self):
        self.assertEqual(quality.blend(60, 0, 0)['overall'],60)
        self.assertEqual(quality.blend(60, 4, 4)['overall'],60)
        fifth=quality.blend(60, 5, 5)
        self.assertAlmostEqual(fifth['overall'],60+40/11)
        self.assertAlmostEqual(fifth['observed_weight'],1/11)
        self.assertGreater(quality.blend(60,15,15)['observed_weight'],.5)
        self.assertLess(quality.blend(60,5,0)['overall'],60)
        self.assertIsNone(quality.blend(None,4,4)['overall'])
        self.assertEqual(quality.blend(None,5,4)['overall'],80)

    def test_outcomes_change_provider_pick_and_actual_effort(self):
        rows=[candidate('initial',90),candidate('measured',70)]
        records=rounds('initial',n=30,passed=False)+rounds('measured',n=30)
        quality.build(rows,records,NOW)
        result=selection.build({'candidates':rows},[])
        self.assertEqual(result['default_worker']['model'],'measured')
        self.assertEqual(result['default_worker']['options'],[{'id':'effort','value':'low'}])
        self.assertEqual(result['providers']['example']['selected']['worker'],result['default_worker'])
        chosen=result['worker'][0]
        self.assertEqual(chosen['quality_n'],30)
        self.assertEqual(chosen['quality_s'],30)
        self.assertAlmostEqual(chosen['quality_score'],quality.blend(70,30,30)['overall'])

    def test_unmeasured_effort_cannot_hide_enough_observed_failures(self):
        row=candidate(aa=90)
        quality.build([row],rounds(n=30,passed=False),NOW)
        chosen=quality.choose(row,[{'id':'effort','value':'high'}])
        self.assertEqual(chosen['effort'],'low')
        self.assertLess(chosen['overall'],30)

    def test_model_summary_marks_active_pool_and_keeps_spent_models_for_all_toggle(self):
        active=candidate('active')
        spent=candidate('spent')
        spent['capacity']['remaining_ratio']=0
        rows=[active,spent]
        result=quality.build(rows,rounds('active',n=5)+rounds('active','high',n=6),NOW)
        selected=selection.build({'candidates':rows},[])
        quality.annotate(result,selected)
        active_rows=[r for r in result['rows'] if r['active']]
        self.assertEqual({r['model'] for r in active_rows},{'active'})
        self.assertEqual(sum(r['representative'] for r in active_rows),1)
        representative=next(r for r in active_rows if r['representative'])
        self.assertEqual(representative['effort'],selected['worker'][0]['effort']['value'])
        self.assertEqual(representative['active_rank'],1)
        self.assertEqual(sum(r['representative'] for r in result['rows']),2)

    def test_boolean_effort_remains_a_native_boolean_for_review_and_work(self):
        row=candidate()
        row['native']['options']=[{'id':'thinking','type':'boolean'}]
        quality.build([row],[],NOW)
        result=selection.build({'candidates':[row]},[{'instance_id':'native','model':'model'}])
        for category in selection.CATEGORIES:
            self.assertEqual(result[category][0]['native']['options'],[{'id':'thinking','value':True}])

    def test_efforts_dated_builds_and_unattributed_work_stay_distinct(self):
        rows=[candidate('model:1017'),candidate('model')]
        records=rounds('model',n=8)+rounds('model:1017','high',n=5,passed=False)
        records.append({**records[0],'id':'unknown-effort','model':'model:1017',
                        'effort_option':None,'effort':'default'})
        result=quality.build(rows,records,NOW)
        dated=[r for r in result['rows'] if r['model']=='model:1017']
        high=next(r for r in dated if r['effort']=='high')
        low=next(r for r in dated if r['effort']=='low')
        untyped=next(r for r in dated if r['effort']=='default')
        self.assertEqual((high['n'],high['passed'],low['n']),(5,0,0))
        self.assertFalse(untyped['selectable'])
        self.assertEqual(quality.choose(rows[0],[{'id':'effort','value':'high'}])['effort'],'high')

    def test_dedup_dates_failures_and_missing_measurements(self):
        rows=[candidate()]
        records=rounds(n=5)
        records[0]['merged']=True
        records[1]['passed']=False
        records[1]['tokens']=None
        records[0]['quota_delta']={'used':.2,'basis':'shared window'}
        result=quality.build(rows,records+[records[0],{**records[0],'id':'future','date':NOW+1},
                                      {**records[0],'id':'stale','date':NOW-quality.MAX_AGE-1}],NOW)
        row=next(r for r in result['rows'] if r['effort']=='low')
        self.assertEqual((row['n'],row['passed'],row['merged'],row['merge_n']),(5,4,1,1))
        self.assertEqual(row['seconds_per_pass'],75)
        self.assertIsNone(row['tokens_per_pass'])
        self.assertIsNone(row['quota_per_pass'])
        self.assertIsNone(row['review_findings'])
        self.assertEqual(row['sources'],['bench'])
        self.assertEqual(row['date'],NOW)
        labels=quality.samples(result)[0][1]
        self.assertNotIn('id',labels)
        self.assertNotIn('task',labels)

    def test_missing_aa_is_not_a_fabricated_prior(self):
        row=candidate(aa=None)
        result=quality.build([row],[],NOW,'producer_unavailable')
        self.assertTrue(all(r['overall'] is None and r['aa'] is None for r in result['rows']))
        self.assertTrue(all(r['basis']=='no evidence yet' for r in result['rows']))
        self.assertEqual(selection.build({'candidates':[row]},[])['worker'][0]['quality_score'],None)


if __name__ == '__main__':
    unittest.main()
