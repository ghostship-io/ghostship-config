"""Panel time semantics: selected-range claims use the time picker, rolling gauges say so."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / 'modules/self-hosted/siem/dashboards'
OWNED = ('autonomous-work.json', 'host.json', 'security.json', 'siem-pipeline.json')


def panels(name):
    return json.loads((DASH / name).read_text())['panels']


class TimeSemantics(unittest.TestCase):
    def test_range_claims_follow_the_time_picker(self):
        page = {p['id']: p for p in panels('autonomous-work.json')}
        for pid in (23, 24):
            expr = page[pid]['targets'][0]['expr']
            # The datasource bounds the search with the picker's start/end, which
            # is exact even for a past range; a relative _time: filter would be
            # evaluated against now and silently show the wrong window.
            self.assertNotIn('_time:', expr)
            self.assertNotIn('event_today', expr)
            self.assertIn('range', page[pid]['title'].lower())

    def test_current_state_panels_are_labelled_as_snapshots(self):
        page = {p['id']: p for p in panels('autonomous-work.json')}
        for pid in (20, 21, 22, 25, 26, 27, 28, 29, 30, 31):
            description = (page[pid].get('description') or '').lower()
            self.assertIn('snapshot', description, page[pid]['title'])
        # The UTC-day cards say they are the UTC day, not the picker.
        for pid in (4, 5):
            description = (page[pid].get('description') or '').lower()
            self.assertIn('utc day', description)
            self.assertIn('picker', description)

    def test_rolling_rates_are_named_as_rolling(self):
        host = {p['id']: p for p in panels('host.json')}
        for pid in (1, 1001):
            self.assertIn('rolling', (host[pid].get('description') or '').lower())
        self.assertIn('rolling', (host[4].get('description') or '').lower())
        for entry in OWNED:
            for panel in panels(entry):
                for target in panel.get('targets', []):
                    expr = target.get('expr', '')
                    if '[5m]' in expr and panel.get('type') == 'timeseries':
                        description = (panel.get('description') or '').lower()
                        self.assertTrue('rolling' in description or 'five-minute' in description,
                                        (entry, panel['title']))
    def test_no_panel_sums_a_rolling_gauge_as_a_range_total(self):
        for entry in OWNED:
            for panel in panels(entry):
                for target in panel.get('targets', []):
                    expr = target.get('expr', '')
                    self.assertNotIn('sum(ghostship_container_memory_bytes', expr.replace(' ', ''))
                    # increase() is only valid on a cumulative counter (_total), never on a
                    # rolling gauge that would otherwise be summed into a fake range total.
                    for match in re.finditer(r'increase\(\s*([a-zA-Z0-9_:]+)', expr):
                        self.assertTrue(match.group(1).endswith('_total'), (entry, panel['title'], match.group(1)))


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(__import__('os').environ.get('GHOSTSHIP_TEST_VLOGS'),
                     'Set GHOSTSHIP_TEST_VLOGS for the selected-range fixture check')
class SelectedRangeFixture(unittest.TestCase):
    """The selected range is the picker's window, including a range ending in the past."""

    def server(self):
        import socket, subprocess, time, urllib.request
        binary = __import__('os').environ['GHOSTSHIP_TEST_VLOGS']
        self.tmp = __import__('tempfile').TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        proc = subprocess.Popen([binary, f'-storageDataPath={self.tmp.name}', f'-httpListenAddr=127.0.0.1:{port}',
                                 '-loggerLevel=ERROR'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5)
        self.addCleanup(stop)
        url = f'http://127.0.0.1:{port}'
        for _ in range(200):
            try:
                urllib.request.urlopen(url + '/health', timeout=0.1).close(); return url
            except OSError:
                time.sleep(0.05)
        self.fail('disposable VictoriaLogs did not start')

    def test_selected_range_window_including_a_past_end(self):
        import json, time, urllib.parse, urllib.request
        url = self.server()
        now = time.time()
        end = now - 3600                      # the picker's "to" is one hour in the past
        rows = []
        for age, tag in ((600, 'recent'), (7200, 'old')):
            rows.append({'host': 'fixture', 'source': 's', 'stream': 'autonomous-work',
                         'message': 'm', 'kind': 'run', 'work_id': tag, 'status': 'running',
                         'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(end - age))})
        urllib.request.urlopen(urllib.request.Request(
            url + '/insert/jsonline?_stream_fields=host,source,stream&_msg_field=message&_time_field=timestamp',
            data=(''.join(json.dumps(r) + '\n' for r in rows)).encode(),
            headers={'Content-Type': 'application/stream+json'}), timeout=5).close()
        time.sleep(2)

        def query(start):
            expr = 'stream:=autonomous-work kind:=run | fields work_id'
            params = {'query': expr, 'start': str(start), 'end': str(end)}
            with urllib.request.urlopen(url + '/select/logsql/query?' + urllib.parse.urlencode(params), timeout=10) as r:
                return {json.loads(line)['work_id'] for line in r.read().splitlines()}

        # The picker's start/end bound the search exactly, including a past end.
        self.assertEqual(query(end - 3600), {'recent'})
        self.assertEqual(query(end - 6 * 3600), {'recent', 'old'})
        self.assertEqual(query(end - 300), set())
        # Deliberately no relative _time: probe here: its interaction with a past
        # end is not something the panel relies on, which is exactly why range
        # panels are bounded by start/end only.

    def test_installed_plugin_expands_range_macro(self):
        import os
        from pathlib import Path as P
        plugin = P(os.environ.get('GHOSTSHIP_TEST_PLUGIN_DIR', '/tmp/grafana-plugins-full')) / 'victoriametrics-logs-datasource' / 'module.js'
        if not plugin.is_file():
            self.skipTest('plugin bundle not available locally')
        source = plugin.read_text()
        # The datasource interpolates the range from scoped vars itself, so a
        # $__range filter is expanded without any custom code of ours.
        self.assertIn('__range', source)
        self.assertIn('applyTemplateVariables', source)
