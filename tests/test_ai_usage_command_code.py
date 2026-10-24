"""Command Code is its own paid, ZDR-only route; estimates are never quota readings."""
import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'modules/self-hosted/ai-usage/collector'))
import catalog
import model_selection
import outcomes
import ranking
import snapshot
import t3source

MODEL = 'deepseek/deepseek-v4.1-flash'
PAIR = ('commandCode', MODEL)
CONFIG = {'driver': 'acpRegistry', 'enabled': True,
          'environment': [{'name': 'CMD_ZDR', 'value': '1'}],
          'config': {'source': 'local', 'commandPath': '/home/t3code/.local/bin/cmd',
                     'commandArgs': ['acp']}}


def epoch(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


class Client:
    def __init__(self, configured=None, models=None):
        self.configured = copy.deepcopy(CONFIG if configured is None else configured)
        self.models = models or [{'slug': MODEL, 'name': 'DeepSeek V4.1 Flash (latest)'}]

    def call(self, method, args):
        if method == 'server.refreshProviders':
            return {'providers': [{'instanceId': 'commandCode', 'driver': 'acpRegistry',
                                   'enabled': True, 'status': 'ready', 'version': '1.88.0',
                                   'models': self.models}]}
        if method == 'server.getConfig':
            return {'settings': {'providerInstances': {'commandCode': self.configured}}}
        raise AssertionError(method)


def build(now, configured=None, free=False):
    context = {}
    reading = t3source._collect_limits(Client(configured), context)
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
    def test_native_route_is_paid_zdr_worker_with_unknown_remaining_usage(self):
        document, row, reading = build(epoch('2026-10-24T12:00:00'))
        self.assertEqual(row['price']['input'], .15)
        self.assertEqual(row['price']['output'], .60)
        self.assertEqual(row['access']['billing'], 'subscription')
        self.assertEqual(row['access']['kind'], 'provider_paid')
        self.assertTrue(row['available'])
        self.assertEqual(row['native']['provider_instance_id'], 'commandCode')
        self.assertEqual(row['native']['model_id'], MODEL)
        self.assertEqual(reading.windows, [])
        self.assertIsNone(row['capacity']['remaining_ratio'])
        self.assertEqual(row['capacity']['source'], 'unknown')
        selected = document['model_selection']['providers']['commandCode']['selected']['worker']
        self.assertEqual(selected, {'instanceId': 'commandCode', 'model': MODEL})
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

    def test_missing_or_unmanaged_zdr_configuration_cannot_be_selected(self):
        variants = [{}, {'config': 'malformed'}, {'environment': 'CMD_ZDR=1'}]
        for field, value in [('environment', []), ('environment', [{'name': 'CMD_ZDR', 'value': '0'}]),
                             ('driver', 'other')]:
            cfg = copy.deepcopy(CONFIG); cfg[field] = value; variants.append(cfg)
        cfg = copy.deepcopy(CONFIG); cfg['config']['commandPath'] = '/usr/bin/cmd'; variants.append(cfg)
        cfg = copy.deepcopy(CONFIG); cfg['config']['commandArgs'] = []; variants.append(cfg)
        cfg = copy.deepcopy(CONFIG); cfg['environment'].append({'name': 'CMD_ZDR', 'value': '0'}); variants.append(cfg)
        for cfg in variants:
            with self.subTest(configured=cfg):
                document, row, _ = build(epoch('2026-10-24T12:00:00'), cfg)
                self.assertFalse(row['native']['available'])
                self.assertIsNone(document['model_selection']['providers']['commandCode']['selected']['worker'])

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
        self.assertNotEqual(row['native']['provider_instance_id'], 'opencode')

    def test_unreviewed_native_models_and_unreadable_configuration_fail_closed(self):
        context = {}
        t3source._collect_limits(Client(models=[{'slug': 'free/unreviewed-model'}]), context)
        self.assertFalse(context['native_models'][('commandCode', 'free/unreviewed-model')]['available'])

        class Unavailable(Client):
            def call(self, method, args):
                if method == 'server.getConfig':
                    raise t3source.T3Error('unavailable')
                return super().call(method, args)
        reading = t3source._collect_limits(Unavailable(), context)
        self.assertEqual(reading.status, 'partial')
        self.assertFalse(context['native_models'][PAIR]['available'])


if __name__ == '__main__':
    unittest.main()
