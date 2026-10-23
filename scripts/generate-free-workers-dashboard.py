#!/usr/bin/env python3
"""Generate Free models from Paid models; refuse drift or paid selectors.

Usage: python3 scripts/generate-free-workers-dashboard.py [--check]
"""

import argparse
import copy
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "modules/self-hosted/siem/dashboards/paid-models.json"
DST = ROOT / "modules/self-hosted/siem/dashboards/free-workers.json"


SUBSTITUTIONS = (
    ('picker_eligible="true",provider!="openrouter"', 'billing=~"free|promotion"'),
    ('picker_eligible="true",provider=~"$provider",provider!="openrouter"',
     'billing=~"free|promotion",provider=~"$provider"'),
    ('billing!~"free|promotion"', 'billing=~"free|promotion"'),
    (',provider!="pi"', ''),
    (',provider!="openrouter"', ''),
)


def free_selectors(dashboard):
    counts = {old: 0 for old, _ in SUBSTITUTIONS}

    def visit(value):
        if isinstance(value, str):
            for old, new in SUBSTITUTIONS:
                counts[old] += value.count(old)
                value = value.replace(old, new)
            return value
        if isinstance(value, list):
            return [visit(v) for v in value]
        if isinstance(value, dict):
            return {k: visit(v) for k, v in value.items()}
        return value

    result = visit(dashboard)
    for old, count in counts.items():
        if count == 0:
            raise ValueError(f"Paid models selector changed or disappeared: {old}")
    raw = json.dumps(result)
    for forbidden in ('picker_eligible=\\"true\\"', 'scope=\\"t3\\"', 'orchestrator_model'):
        if forbidden in raw:
            raise ValueError(f"Paid selector remains in free dashboard: {forbidden}")
    return result


def compact_rows(original, kept):
    # Rows can contain multiple cards. Remove a row's vertical band only when
    # the whole row was removed, and never consume the next occupied row.
    rows = {}
    for panel in original:
        if 'gridPos' in panel:
            pos = panel['gridPos']
            rows[pos['y']] = max(rows.get(pos['y'], 0), pos['h'])
    occupied = {p['gridPos']['y'] for p in kept if 'gridPos' in p}
    starts = sorted(rows)
    removed = []
    for i, y in enumerate(starts):
        if y not in occupied:
            end = min(y + rows[y], starts[i + 1]) if i + 1 < len(starts) else y + rows[y]
            removed.append((y, end))
    for panel in kept:
        if 'gridPos' in panel:
            pos = panel['gridPos']
            y = pos['y']
            pos['y'] -= sum(end - start for start, end in removed if end <= y)


def generate():
    dashboard = json.loads(SRC.read_text())

    # 1. Metadata
    dashboard["uid"] = "ghostship-free-workers"
    dashboard["title"] = "Free models"
    dashboard["description"] = "Free pool generated from Paid models · public tasks only"
    dashboard['links'] = [
        {'title': title, 'type': 'link', 'url': '/d/' + uid, 'targetBlank': False}
        for title, uid in [('Providers', 'ghostship-ai-usage'),
                           ('Paid models', 'ghostship-paid-models'),
                           ('Free models', 'ghostship-free-workers')]
    ]

    dashboard["templating"]["list"] = [
        v for v in dashboard.get("templating", {}).get("list", [])
        if v.get("name") != "orchestrator_model"
    ]
    original = copy.deepcopy(dashboard.get("panels", []))
    panels = []
    for panel in dashboard.get("panels", []):
        if panel.get("id") in {230, 231} or panel.get("repeat") == "orchestrator_model":
            continue

        if panel.get("id") == 200:
            panel["options"]["content"] = (
                '<div style="font-family:Inter,system-ui,sans-serif;max-width:100%;overflow-wrap:anywhere">'
                '<strong>Free models</strong>'
                '<span style="font-size:11px;color:#8b8f99"> · Free worker pool · one selection per provider · Public tasks only</span>'
                '</div>'
            )
        elif panel.get("id") == 232:
            panel["options"]["content"] = (
                '<div style="font-family:Inter,system-ui,sans-serif;max-width:100%;overflow-wrap:anywhere">'
                '<strong>Free worker models</strong>'
                '<span style="font-size:11px;color:#8b8f99"> · Public-only policy · Exhausted routes greyed out · Paced Availability · selected per provider</span>'
                '</div>'
            )
        elif panel.get("id") == 234:
            panel["options"]["content"] = (
                '<div style="font-family:Inter,system-ui,sans-serif;max-width:100%;overflow-wrap:anywhere">'
                '<strong>Free provider capacity</strong>'
                '<span style="font-size:11px;color:#8b8f99"> · Short windows are blue above zero. Only weekly/monthly windows are paced.</span>'
                '</div>'
            )

        panels.append(panel)

    compact_rows(original, panels)
    dashboard["panels"] = panels
    dashboard = free_selectors(dashboard)
    return json.dumps(dashboard, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if output differs from committed free-workers.json")
    args = parser.parse_args()

    generated = generate()

    if args.check:
        if not DST.exists():
            print(f"Error: {DST} does not exist", file=sys.stderr)
            sys.exit(1)
        committed = DST.read_text()
        if committed != generated:
            diff = "".join(
                difflib.unified_diff(
                    committed.splitlines(keepends=True),
                    generated.splitlines(keepends=True),
                    fromfile="committed",
                    tofile="generated",
                )
            )
            print(f"Error: {DST} differs from generator output:\n{diff}", file=sys.stderr)
            print("Run: python3 scripts/generate-free-workers-dashboard.py", file=sys.stderr)
            sys.exit(1)
        print("OK: free-workers.json matches generator output")
        sys.exit(0)

    DST.write_text(generated)
    print(f"Wrote {DST}")


if __name__ == "__main__":
    main()
