"""Owner-approved free routes are first-choice workers until their limit is spent."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))

import model_selection

NOW = '2026-10-24T02:00:00Z'


def candidate(provider, model, quality, *, billing='subscription', remaining=1.0,
              pace='on_pace', mapped=True, allowance=None, available=True):
    return {
        'provider': provider, 'model': model, 'display_name': model,
        'available': available, 'quota_state': 'available' if available else 'exhausted',
        'capacity': {'remaining_ratio': remaining, 'pace_state': pace},
        'quality_score': quality, 'quality_p': quality / 100, 'quality_basis': 'AA only',
        'access': {'billing': billing},
        'native': ({'mapped': True, 'provider_instance_id': provider, 'model_id': model,
                    'available': True, 'options': [{'id': 'effort', 'values': ['low', 'high']}]}
                   if mapped else {'mapped': False}),
        **({'allowance': allowance} if allowance else {}),
    }


def policy(entries):
    return {'policy': {'model_selection': {'approved_free_workers': entries}}}


APPROVED = [{'provider': 'opencode', 'model': 'big-pickle', 'allow_training': True}]


class ApprovedFreeTests(unittest.TestCase):
    def build(self, candidates, entries=APPROVED, quota=None):
        return model_selection.build(
            {'generated_at': NOW, 'candidates': candidates,
             **({'quota': {'accounts': quota}} if quota else {})}, [], evidence=policy(entries))

    def test_an_approved_free_route_leads_a_paid_route_while_it_has_limit(self):
        paid = candidate('codex', 'gpt-6.1-sol', 55, mapped=False)
        free = candidate('opencode', 'big-pickle', 40, billing='free', remaining=0.6, mapped=False)
        result = self.build(
            [paid, free],
            quota={'opencode': [{'kind': 'monthly', 'remaining_ratio': 0.6,
                                 'check_at': '2026-10-24T01:50:00Z',
                                 'reset_at': '2026-11-01T00:00:00Z', 'source': 'pool'}]})
        self.assertEqual(result['worker'][0]['model'], 'big-pickle')
        row = result['worker'][0]
        self.assertTrue(row['approved_free'])
        self.assertFalse(row['overspent'])
        self.assertTrue(row['selection_eligible'])
        self.assertIn('approved free worker', row['pick_reason'])
        self.assertIn('binding monthly', row['pick_reason'])

    def test_a_spent_approved_free_route_falls_back_to_paid(self):
        paid = candidate('codex', 'gpt-6.1-sol', 55, mapped=False)
        free = candidate('opencode', 'big-pickle', 90, billing='free', remaining=0.0,
                         mapped=False, available=False)
        result = self.build([paid, free])
        models = [row['model'] for row in result['worker']]
        self.assertEqual(models, ['gpt-6.1-sol', 'big-pickle'])
        spent = result['worker'][1]
        self.assertTrue(spent['overspent'])
        self.assertFalse(spent['available'])

    def test_an_overspent_free_route_yields_to_paid(self):
        paid = candidate('codex', 'gpt-6.1-sol', 55, mapped=False)
        free = candidate('opencode', 'big-pickle', 90, billing='free', remaining=0.7,
                         pace='far_behind', mapped=False)
        result = self.build([paid, free])
        self.assertEqual(result['worker'][0]['model'], 'gpt-6.1-sol')
        self.assertTrue(result['worker'][1]['overspent'])
        self.assertIn('overspent; fall back to paid', result['worker'][1]['pick_reason'])

    def test_a_route_the_owner_did_not_approve_does_not_outrank_paid(self):
        paid = candidate('codex', 'gpt-6.1-sol', 55, mapped=False)
        free = candidate('opencode', 'mystery-free', 99, billing='free', mapped=False)
        result = self.build([paid, free])
        self.assertEqual(result['worker'][0]['model'], 'gpt-6.1-sol')
        self.assertIsNone(result['worker'][1]['approved_free'])
        self.assertFalse(result['worker'][1]['free_worker'])

    def test_training_allowed_approval_overrides_the_generic_data_policy(self):
        allowance = {'budgets': [{'kind': 'session', 'requests': 1000, 'unit': 'requests'}],
                     'training': 'used', 'retention': 'not_zdr', 'sensitive_ok': False,
                     'source': 'provider page', 'checked_at': NOW}
        free = candidate('opencode', 'big-pickle', 40, billing='free', mapped=False,
                         allowance=allowance)
        approved = self.build([free], [{'provider': 'opencode', 'model': 'big-pickle',
                                        'allow_training': True}])
        self.assertTrue(approved['worker'][0]['selection_eligible'])
        refused = self.build([free], [{'provider': 'opencode', 'model': 'big-pickle',
                                       'allow_training': False}])
        self.assertFalse(refused['worker'][0]['selection_eligible'])
        self.assertIn('data policy', refused['worker'][0]['selection_reason'])

    def test_the_approval_is_published_with_its_source(self):
        free = candidate('opencode', 'big-pickle', 40, billing='free', mapped=False)
        result = self.build([free])
        approval = result['worker'][0]['approved_free']
        self.assertEqual(approval['source'], 'owner runtime policy: approved_free_workers')
        self.assertTrue(approval['allow_training'])


if __name__ == '__main__':
    unittest.main()
