"""Sonnet shares Claude's weekly budget without consuming its review reserve."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'modules/self-hosted/ai-usage/collector'))
import model_selection

NOW = 1_800_000_000
WEEK = 7 * 86400
SONNET = 'claude-sonnet-5-5'
OPUS = 'claude-opus-5-5'


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def candidate(provider, model, score=80):
    return {'provider': provider, 'model': model, 'available': True, 'quality_score': score,
            'native': {'mapped': True, 'available': True, 'provider_instance_id':
                       'claudeAgent' if provider == 'claude' else provider, 'model_id': model,
                       'options': [{'id': 'effort', 'values': ['medium', 'high']},
                                   {'id': 'fastMode', 'type': 'boolean'}]},
            'capacity': {'remaining_ratio': .9}, 'access': {'billing': 'subscription'},
            'price': {'input': 1, 'output': 5}}


class ClaudeWorkerTests(unittest.TestCase):
    def setUp(self):
        self.week = {'kind': 'weekly', 'quota_id': 'seven_day', 'remaining_ratio': .8,
                     'check_at': iso(NOW), 'reset_at': iso(NOW + WEEK / 2),
                     'duration_seconds': WEEK}
        self.policy = {'roles': {'orchestrator': [{'instance_id': 'claudeAgent', 'model': OPUS}]},
                       'model_selection': {'provider_roles': {'claude': ['orchestrator', 'worker']},
                         'worker_builds': {'claude': SONNET}, 'excluded_pools': ['claude:fable'],
                         'worker_pool_guards': {'claude': {'kind': 'weekly',
                           'minimum_remaining_ratio': .2, 'require_pace_headroom': True}}}}

    def build(self, windows=None):
        snapshot = {'generated_at': iso(NOW), 'model_quality': {},
                    'candidates': [candidate('claude', SONNET, 95), candidate('claude', OPUS, 99),
                                   candidate('claude', 'claude-fable-5', 100),
                                   candidate('codex', 'gpt-6.1-sol', 80)],
                    'quota': {'accounts': {'claude': [self.week] if windows is None else windows}}}
        return model_selection.build(snapshot, self.policy['roles']['orchestrator'],
                                     evidence={'policy': self.policy})

    def test_sonnet_only_worker_and_opus_review_survives_the_shared_guard(self):
        value = self.build()
        group = value['providers']['claude']
        self.assertEqual(group['selected']['worker']['model'], SONNET)
        self.assertEqual(group['selected']['orchestrator']['model'], OPUS)
        self.assertNotIn('claude-fable-5', [r['model'] for r in value['worker']])
        self.assertEqual(group['selected']['worker']['options'],
                         [{'id': 'effort', 'value': 'high'}, {'id': 'fastMode', 'value': False}])

        self.week['remaining_ratio'] = .4  # Below the .5 time-proportional line.
        value = self.build()
        self.assertIsNone(value['providers']['claude']['selected']['worker'])
        self.assertEqual(value['providers']['claude']['selected']['orchestrator']['model'], OPUS)
        sonnet = next(r for r in value['worker'] if r['model'] == SONNET)
        self.assertFalse(sonnet['available'])
        self.assertEqual(sonnet['state'], 'reserved')
        self.assertTrue(sonnet['selection_eligible'])  # Still listed, grey, until headroom returns.
        self.assertEqual(value['default_worker']['model'], 'gpt-6.1-sol')

    def test_reserve_and_pace_boundaries_are_both_inclusive(self):
        for remaining, expected, allowed in ((.2, .1, True), (.199, .1, False),
                                             (.5, .5, True), (.499, .5, False)):
            with self.subTest(remaining=remaining, expected=expected):
                self.week.update(remaining_ratio=remaining, reset_at=iso(NOW + WEEK * expected))
                picked = self.build()['providers']['claude']['selected']['worker']
                self.assertEqual(picked is not None, allowed)

    def test_missing_stale_expired_or_unreadable_weekly_quota_withholds_worker(self):
        invalid = [[], [{**self.week, 'check_at': iso(NOW - 1801)}],
                   [{**self.week, 'reset_at': iso(NOW)}], [{**self.week, 'duration_seconds': None}],
                   [{**self.week, 'remaining_ratio': None}],
                   [{**self.week, 'check_at': iso(NOW + 3600)}]]
        for windows in invalid:
            with self.subTest(windows=windows):
                self.assertIsNone(self.build(windows)['providers']['claude']['selected']['worker'])

    def test_unused_fable_or_short_window_cannot_supply_review_headroom(self):
        ignored = [{**self.week, 'not_used': True, 'quota_id': 'seven_day_fable'},
                   {**self.week, 'kind': 'session', 'quota_id': 'five_hour'}]
        self.assertIsNone(self.build(ignored)['providers']['claude']['selected']['worker'])
        self.week['remaining_ratio'] = .1
        self.assertIsNone(self.build([self.week] + ignored)['providers']['claude']['selected']['worker'])

    def test_host_preferences_cannot_erase_or_replace_the_declared_claude_worker(self):
        model_selection.apply_worker_builds(self.policy, {'ollama': 'ollama-cloud/model:dated'})
        self.assertEqual(self.policy['model_selection']['worker_builds'],
                         {'claude': SONNET, 'ollama': 'ollama-cloud/model:dated'})
        with self.assertRaisesRegex(ValueError, 'conflicts with runtime policy'):
            model_selection.apply_worker_builds(self.policy, {'claude': OPUS})

    def test_exhaustion_keeps_its_spent_state_and_never_becomes_a_review_reservation(self):
        self.week['remaining_ratio'] = 0
        value = self.build()
        row = next(r for r in value['worker'] if r['model'] == SONNET)
        self.assertFalse(row['available'])
        self.assertEqual(row['state'], 'exhausted')
        self.assertEqual(row['reason'], 'quota_exhausted')

    def test_claude_worker_cannot_be_enabled_without_a_valid_review_guard(self):
        for guard in (None, {}, {'kind': 'weekly', 'minimum_remaining_ratio': True,
                                'require_pace_headroom': True}):
            with self.subTest(guard=guard):
                self.policy['model_selection']['worker_pool_guards']['claude'] = guard
                self.assertIsNone(self.build()['providers']['claude']['selected']['worker'])


if __name__ == '__main__':
    unittest.main()
