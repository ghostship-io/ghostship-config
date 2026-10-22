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
            self.assertIn('_time:$__range', expr, 'a selected-range panel must use the time picker')
            self.assertNotIn('_time:24h', expr)
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
