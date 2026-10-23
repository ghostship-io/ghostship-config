"""Positive quota stays available until it is exhausted."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import ranking


class WorkerEligibilityTests(unittest.TestCase):
    def test_positive_quota_is_usable_until_exactly_exhausted(self):
        for remaining in (.001, .049, .05, .051, 0):
            with self.subTest(remaining=remaining):
                rows = ranking.rank_models(models=[('example', 'model')], catalog=None,
                    quota_windows={'example': [ranking.QuotaWindow('weekly', 1-remaining, 2000,
                        duration_seconds=604800, observed_at=1000)]},
                    free_models=set(), usage_tokens={}, now=1000)
                self.assertTrue(rows)
                self.assertEqual(any(row.available for row in rows), remaining > 0)

    def test_fresh_reported_quota_recovers_after_an_older_usage_limit(self):
        failure={'scope':'account','target':'example','reason':'account_usage_limit',
                 'label':'quota spent','observed_at':999}
        windows=[ranking.QuotaWindow('weekly', .5, 2000,
            duration_seconds=604800,observed_at=1000)]
        rows=ranking.rank_models(models=[('example','model')],catalog=None,
            quota_windows={'example':windows},free_models=set(),usage_tokens={},
            observed_failures=[failure],now=1000)
        self.assertTrue(any(row.available for row in rows))
        self.assertTrue(all(not row.observed_failure for row in rows))

    def test_old_or_inferred_readings_and_other_failures_cannot_grant_recovery(self):
        for observed,basis,reason,used,model_failure in (
            (998,'','account_usage_limit',.5,False),
            (1000,'inferred','account_usage_limit',.5,False),
            (1000,'published','account_usage_limit',.5,False),
            (1000,'','provider_error',.5,False),
            (1000,'','account_usage_limit',1,False),
            (1000,'','account_usage_limit',.5,True)):
            with self.subTest(observed=observed,basis=basis,reason=reason,used=used,model_failure=model_failure):
                failures=[{'scope':'account','target':'example','reason':reason,
                    'label':'unavailable','observed_at':999}]
                if model_failure:failures.append({'scope':'model','target':'model',
                    'reason':'route_startup_failed','label':'runtime unavailable','observed_at':999})
                rows=ranking.rank_models(models=[('example','model')],catalog=None,
                    quota_windows={'example':[ranking.QuotaWindow('weekly',used,2000,
                        duration_seconds=604800,observed_at=observed,basis=basis)]},
                    free_models=set(),usage_tokens={},observed_failures=failures,now=1000)
                self.assertFalse(any(row.available for row in rows))
