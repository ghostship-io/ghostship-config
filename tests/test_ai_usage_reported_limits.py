"""The managed bearer projection supplies reported subscription windows."""
import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'modules/self-hosted/ai-usage/collector'))
import main
import snapshot


class ReportedLimitsTests(unittest.TestCase):
    def test_rotating_plain_bearer_reaches_the_real_limit_reader(self):
        class Client:
            def __init__(self, base, token, **options):
                self.token = token
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def call(self, method, payload):
                if method == 'server.refreshProviders':
                    return {'providers': [{'instanceId': 'claudeAgent', 'status': 'ready',
                        'usageLimits': {'checkedAt': '2026-01-01T12:00:00Z', 'windows': [
                            {'id': 'five_hour', 'kind': 'session', 'usedPercent': 17,
                             'resetsAt': '2026-01-01T14:00:00Z', 'windowDurationMins': 300},
                            {'id': 'seven_day', 'kind': 'weekly', 'usedPercent': 45,
                             'resetsAt': '2026-01-05T12:00:00Z', 'windowDurationMins': 10080}]}}]}
                return {}
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'bearer'
            token.write_text('synthetic-rotating-bearer\n')
            with patch.object(main, 'T3_SESSION_FILE', str(token)), patch.object(
                    main, 'resolve_t3_base_url', return_value='http://localhost'), patch.object(
                    main, 'T3Client', Client):
                results = main.collect_t3(1767268800, None, {})
        self.assertEqual(results[0].status, 'ok')
        self.assertEqual([(w['provider'], w['quotaId'], w['usedRatio']) for w in results[0].windows],
                         [('claude', 'five_hour', .17), ('claude', 'seven_day', .45)])

    def test_collector_and_picker_share_the_managed_token_projection(self):
        self.assertEqual(main.T3_SESSION_FILE, '/run/ghostship-integrations/t3-token')
        with tempfile.TemporaryDirectory() as folder:
            token = Path(folder) / 'bearer'
            for value in ('first-synthetic-token', 'rotated-synthetic-token'):
                token.write_text(value + '\n')
                self.assertEqual(main.read_session_token(str(token)), value)

    def test_missing_reported_limits_are_not_learning(self):
        samples = snapshot.account_window_samples({'quota': {'accounts': {'claude': [], 'codex': [],
            'opencode-go': [], 'unknown-free-provider': []}}})
        learning = {labels['account'] for name, labels, value in samples
                    if name == 'ghostship_ai_account_window_learning'}
        self.assertEqual(learning, {'unknown-free-provider'})
        missing = {labels['account'] for name, labels, value in samples
                   if name == 'ghostship_ai_account_window_missing'}
        self.assertEqual(missing, {'claude', 'codex', 'opencode-go'})

    def test_visible_capacity_excludes_free_only_openrouter_and_distinguishes_missing(self):
        page = json.loads((Path(__file__).resolve().parents[1] /
            'modules/self-hosted/siem/dashboards/ai-usage.json').read_text())
        panel = next(p for p in page['panels'] if p['id'] == 210)
        code = "const helpers={};const context={handlebars:{registerHelper:(k,v)=>helpers[k]=v}};"
        code += "new Function('context'," + json.dumps(panel['options']['helpers']) + ")(context);"
        code += "console.log(JSON.stringify({cards:helpers.capacityCards([{account:'openrouter',kind:'daily',quota_id:'daily',field:'left',value:.8}],0),learning:helpers.learningLine([{account:'claude',field:'missing',value:1}]),missing:helpers.missingLimitsLine([{account:'claude',field:'missing',value:1}])}));"
        value=json.loads(subprocess.check_output(['node','-e',code],text=True))
        self.assertEqual(value, {'cards': [], 'learning': [], 'missing': [{'text': 'Claude'}]})
        self.assertIn('Reported limits unavailable:', panel['options']['content'])
        self.assertIn('account!="openrouter"', panel['targets'][0]['expr'])
