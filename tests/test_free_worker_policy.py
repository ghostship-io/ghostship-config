"""Keep paid routes and removed policy switches out of the free-worker config."""
import json
from pathlib import Path
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / 'modules/self-hosted'


class FreeWorkerPolicyTests(unittest.TestCase):
    def test_free_pool_has_no_paid_subscription_routes_or_expiring_owner_grants(self):
        pool = json.loads((DIRECTORY / 'inference-pool.json').read_text())
        self.assertFalse({'opencode-go', 'ollama-cloud', 'antigravity'} & pool['providers'].keys())
        for provider, account in pool['providers'].items():
            with self.subTest(provider=provider):
                self.assertFalse({'workload_grant', 'china_hosting_workloads',
                                  'china_hosting_opt_in', 'authorization'} & account.keys())

    def test_native_worker_catalog_enables_only_explicit_zero_price_zen_models(self):
        scope = json.loads((DIRECTORY / 'free-worker-models.json').read_text())
        catalog = json.loads((DIRECTORY / 'free-worker-native-catalog.json').read_text())
        self.assertEqual(set(catalog), {'opencode'})
        enabled = {name for name, allow in scope.items() if allow}
        self.assertTrue(enabled)
        self.assertEqual(set(catalog['opencode']['models']), enabled)
        for name in enabled:
            with self.subTest(model=name):
                cost = catalog['opencode']['models'][name]['cost']
                self.assertEqual(cost['input'], 0)
                self.assertEqual(cost['output'], 0)
