"""Command Code is its own paid, ZDR-only route; estimates are never quota readings."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import catalog
import command_code
import model_selection
import outcomes
import ranking
import snapshot
import t3source

MODEL = 'deepseek/deepseek-v4.1-flash'
SLUG = 'command-code/' + MODEL
PAIR = ('commandCode', MODEL)
PROVIDER = {
    'name': 'Command Code GOAT',
    'package': '@ai-sdk/openai-compatible',
    'settings': {
        'baseURL': command_code.BASE_URL,
        'apiKey': '{env:COMMAND_CODE_API_KEY}',
    },
    'headers': {'x-cmd-zdr': '1'},
    'models': {MODEL: {'name': 'DeepSeek V4.1 Flash (latest)'}},
}
CONFIG = {
    'providers': {'command-code': PROVIDER},
    'enabled_providers': ['ollama-cloud', 'opencode-go', 'command-code'],
}


def epoch(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


def projected(value='set'):
    return command_code.KEY_ENV + '=' + value + '\n'


def route(config=None, key=None):
    """A temporary T3 home with the managed OpenCode route and projection."""
    root = Path(tempfile.mkdtemp())
    directory = root / '.config/opencode'
    directory.mkdir(parents=True)
    if config is not False:
        (directory / 'opencode.jsonc').write_text(json.dumps(CONFIG if config is None else config))
    secrets = root / 't3code.env'
    if key is not False:
        secrets.write_text(projected() if key is None else key)
    return str(root), str(secrets)


class Client:
    def __init__(self, models=None):
        self.models = models or [{'slug': SLUG, 'name': 'DeepSeek V4.1 Flash (latest)'}]

    def call(self, method, args):
        if method == 'server.refreshProviders':
            return {'providers': [{'instanceId': 'opencode', 'driver': 'opencode',
                                   'enabled': True, 'status': 'ready',
                                   'models': self.models}]}
        raise AssertionError(method)


def build(now, config=None, key=None, free=False, models=None):
    home, secrets = route(config, key)
    context = {'t3_home': home, 'secrets_env': secrets}
    reading = t3source._collect_limits(Client(models), context)
    records = [ranking.ModelRecord(*PAIR), ranking.ModelRecord('codex', 'gpt-6.1-sol'),
               ranking.ModelRecord('ollama', 'deepseek-v4.1-flash:1017')]
    native = dict(context['native_models'])
    native[('codex', 'gpt-6.1-sol')] = {'providerInstance': 'codex', 'modelId': 'gpt-6.1-sol'}
    native[('ollama', 'deepseek-v4.1-flash:1017')] = {
        'providerInstance': 'opencode', 'modelId': 'ollama-cloud/deepseek-v4.1-flash:1017'}
    prices = catalog.Catalog({'openai': {'models': {'gpt-6.1-sol': {
        'cost': {'input': 1, 'output': 2, 'cache_read': .1}}}}})
    ranked = ranking.rank_models(models=records, catalog=prices, quota_windows={},
                                 free_models=[PAIR] if free else [], native_models=native, now=now)
    document = snapshot.build_snapshot(now=now, sources=[], ranked=ranked,
        native_models=native, catalog=prices, free_models=[PAIR] if free else [])
    document['model_quality'] = {}
    document['model_selection'] = model_selection.build(document, [])
    row = next(r for r in document['candidates'] if (r['provider'], r['model']) == PAIR)
    return document, row, reading


class CommandCodeWorkerTests(unittest.TestCase):
    def test_opencode_route_is_paid_zdr_worker_with_unknown_remaining_usage(self):
        document, row, reading = build(epoch('2026-10-24T12:00:00'))
        self.assertEqual(row['price']['input'], .15)
        self.assertEqual(row['price']['output'], .60)
        self.assertEqual(row['access']['billing'], 'subscription')
        self.assertEqual(row['access']['kind'], 'provider_paid')
        self.assertTrue(row['available'])
        # The vendor's own model id stays the picker's identity; T3 Code is
        # reached through its OpenCode instance and the prefixed slug.
        self.assertEqual(row['native']['provider_instance_id'], 'opencode')
        self.assertEqual(row['native']['model_id'], SLUG)
        self.assertEqual(reading.windows, [])
        self.assertIsNone(row['capacity']['remaining_ratio'])
        self.assertEqual(row['capacity']['source'], 'unknown')
        selected = document['model_selection']['providers']['commandCode']['selected']['worker']
        self.assertEqual(selected, {'instanceId': 'opencode', 'model': SLUG})
        estimates = row['command_code']['estimated_allowances']
        self.assertEqual([(r['kind'], r['requests']) for r in estimates],
                         [('five_hour', 41000), ('weekly', 103000), ('monthly', 205000)])
        self.assertTrue(all(r['estimated'] and r['unit'] == 'requests' for r in estimates))
        self.assertIsNone(row['command_code']['resolved_build'])
        self.assertTrue(row['command_code']['alias_can_move'])
        self.assertEqual(row['command_code']['vendor_build_evidence']['build'], '1017')
        self.assertEqual(row['quality_n'], 0)
        self.assertEqual(row['quality_basis'], 'default prior')
        self.assertIn('not evaluated', row['command_code']['harness_quality'])
        worker = next(r for r in document['model_selection']['worker'] if r['provider'] == 'commandCode')
        self.assertEqual(worker['provider_terms']['estimated_allowances'], estimates)

    def test_exact_utc_peak_boundaries_and_weekends(self):
        for when, peak in [('2026-10-23T00:59:59', False), ('2026-10-23T01:00:00', True),
                           ('2026-10-23T03:59:59', True), ('2026-10-23T04:00:00', False),
                           ('2026-10-23T06:00:00', True), ('2026-10-23T09:59:59', True),
                           ('2026-10-23T10:00:00', False), ('2026-10-24T02:00:00', False),
                           ('2026-10-25T07:00:00', False), ('2026-10-26T01:00:00', True)]:
            with self.subTest(when=when):
                _, row, _ = build(epoch(when))
                self.assertEqual((row['price']['input'], row['price']['output']),
                                 (.30, 1.20) if peak else (.15, .60))
                self.assertEqual(row['price']['period'], 'peak' if peak else 'off_peak')

    def test_unverified_route_cannot_be_selected(self):
        variants = [
            ('no provider', lambda c: c['providers'].pop('command-code')),
            ('literal key', lambda c: c['providers']['command-code']['settings'].update(apiKey='literal')),
            ('wrong host', lambda c: c['providers']['command-code']['settings'].update(
                baseURL='https://api.example.invalid/provider/v1')),
            ('no zdr', lambda c: c['providers']['command-code'].pop('headers')),
            ('zdr off', lambda c: c['providers']['command-code'].update(
                headers={'x-cmd-zdr': '0'})),
            ('not enabled', lambda c: c.update(enabled_providers=['ollama-cloud'])),
            ('disabled', lambda c: c.update(disabled_providers=['command-code'])),
        ]
        for label, mutate in variants:
            config = copy.deepcopy(CONFIG)
            mutate(config)
            with self.subTest(case=label):
                document, row, _ = build(epoch('2026-10-24T12:00:00'), config)
                # The route itself is unverified, so no Command Code model is
                # admitted as a native route; visibility is separate.
                self.assertFalse(row['native']['available'])
                self.assertFalse(row['available'])
                self.assertIn('ZDR', row['availability']['reason'])
                self.assertIsNone(document['model_selection']['providers']['commandCode']['selected']['worker'])
        for label, key in [('empty key', projected('')),
                           ('missing key', 'OLLAMA_API_KEY=\n'),
                           ('no projection', False)]:
            with self.subTest(case=label):
                document, row, _ = build(epoch('2026-10-24T12:00:00'), key=key)
                self.assertFalse(row['available'])
                self.assertIsNone(document['model_selection']['providers']['commandCode']['selected']['worker'])

    def test_malformed_or_absent_config_is_unverified(self):
        for config in (False, {'providers': 'malformed'}, {'providers': {'command-code': 'malformed'}}):
            with self.subTest(config=config):
                home, secrets = route(config)
                self.assertFalse(command_code.configured(home, secrets))
        self.assertFalse(command_code.configured('', ''))

    def test_anthropic_route_keeps_the_same_provider_identity(self):
        self.assertEqual(command_code.is_model('command-code-anthropic/claude-sonnet-5-5'), True)
        self.assertEqual(t3source.split_model('opencode', 'command-code-anthropic/claude-sonnet-5-5'),
                         ('commandCode', 'claude-sonnet-5-5'))
        self.assertFalse(command_code.is_worker_route('commandCode', 'claude-sonnet-5-5'))

    def test_no_free_route_or_inherited_ollama_outcome_identity(self):
        document, row, _ = build(epoch('2026-10-24T12:00:00'), free=True)
        self.assertEqual(row['access']['billing'], 'subscription')
        self.assertNotIn('free', row['tiers'])
        identities = {'models': {'deepseek-alias': {'model': 'deepseek-v4.1-flash',
                        'routes': ['ollama/deepseek-v4.1-flash']}}}
        command = outcomes.identity_of(*PAIR, identities)
        self.assertNotEqual(command, outcomes.identity_of('ollama', 'deepseek-v4.1-flash', identities))
        self.assertNotEqual(command, outcomes.identity_of('ollama', 'deepseek-v4.1-flash:1017', identities))
        self.assertEqual(command, outcomes.identity_of_round('commandCode/' + MODEL, identities))

    def test_other_native_models_keep_their_own_access_evidence(self):
        free = ('commandCode', 'stealth/current:free')
        unknown = ('commandCode', 'vendor/new-current')
        home, secrets = route()
        context = {'t3_home': home, 'secrets_env': secrets}
        t3source._collect_limits(Client(models=[{'slug': 'command-code/' + pair[1]}
                                 for pair in (PAIR, free, unknown)]), context)
        native = context['native_models']
        prices = catalog.Catalog({})
        ranked = ranking.rank_models(models=[ranking.ModelRecord(*pair) for pair in native],
            catalog=prices, quota_windows={}, free_models=[free], native_models=native,
            now=epoch('2026-10-24T12:00:00'))
        result = snapshot.build_snapshot(now=epoch('2026-10-24T12:00:00'), sources=[],
            ranked=ranked, native_models=native, catalog=prices, free_models=[free])
        rows = {row['model']: row for row in result['candidates']}
        self.assertEqual(set(rows), {pair[1] for pair in (PAIR, free, unknown)})
        # The verified route admits every model it serves; only the reviewed
        # DeepSeek route can be the paid worker, so the rest stay unselectable.
        self.assertTrue(all(row['native']['available'] for row in rows.values()))
        self.assertEqual(rows[free[1]]['access']['kind'], 'provider_paid')
        self.assertEqual(rows[unknown[1]]['access']['kind'], 'provider_paid')
        for pair in (free, unknown):
            self.assertNotIn('not verified', rows[pair[1]]['availability']['reason'])
            self.assertNotIn('command_code', rows[pair[1]])

    def test_full_native_catalog_preserves_readiness_and_unknown_terms(self):
        home, secrets = route()
        context = {'t3_home': home, 'secrets_env': secrets}
        t3source._collect_limits(Client(models=[{'slug': 'command-code/free/unreviewed-model'}]), context)
        self.assertTrue(context['native_models'][('commandCode', 'free/unreviewed-model')]['available'])

        # An unreadable OpenCode config leaves the catalog visible but cannot
        # prove the ZDR route, so nothing on it is admitted.
        home, secrets = route(False)
        context = {'t3_home': home, 'secrets_env': secrets}
        reading = t3source._collect_limits(Client(), context)
        self.assertEqual(reading.status, 'ok')
        self.assertFalse(context['native_models'][PAIR]['available'])
        self.assertFalse(context['native_models'][PAIR]['commandCodePolicyVerified'])


if __name__ == '__main__':
    unittest.main()
