#!/usr/bin/env python3
"""Generate Free models from Paid models; refuse drift or paid selectors.

Usage: python3 scripts/generate-free-workers-dashboard.py [--check]
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Height of the free selection lane in Grafana grid units; tune with the screenshots.
FREE_LANE_HEIGHT = 15
FREE_QUALITY_HEIGHT = 16
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


# Free providers whose whole pool is blocked have no selectable model. They stay
# visible as a grey card instead of silently disappearing from the page.
BLOCKED_QUERY = (
    '\n or label_replace(label_replace((ghostship_ai_provider_free_models{state="unavailable",provider=~"$provider"} > 0)'
    ' unless on(provider) (ghostship_ai_provider_free_models{state="available"} > 0),'
    ' "field", "free_blocked", "", ""), "category", "worker", "", "")'
)
BLOCKED_HELPER = """
context.handlebars.registerHelper('freeBlocked', function(rows) {
  const names = {opencode:'OpenCode Zen','cloudflare-workers-ai':'Cloudflare','kilo-keyed':'Kilo (keyed)',nvidia:'NVIDIA',ovh:'OVH',zai:'Zai'};
  return (rows || []).filter(row => row && row.field === 'free_blocked' && row.provider && Number(row.value) > 0)
    .map(row => ({provider: row.provider, count: Number(row.value),
      name: names[row.provider] || String(row.provider).charAt(0).toUpperCase() + String(row.provider).slice(1),
      icon: String(row.provider).charAt(0).toUpperCase()}))
    .sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
});
"""
BLOCKED_CARD = (
    '{{#each (freeBlocked data)}}<article class="selection-card restricted blocked" data-provider="{{this.provider}}">'
    '<div class="sc-h"><span class="ico">{{this.icon}}</span><span class="model-provider">{{this.name}}</span></div>'
    '<h3>No model available</h3><div class="reason">{{this.count}} models blocked</div></article>{{/each}}</div></section>'
)
FREE_STYLES = (
    ".selection-card.blocked .reason{display:block}"
    ".selection-card .capacity-graph.open .graph-label{margin-top:5px}"
    "@media (max-width:768px){.selection-card .capacity-graph,.selection-card .model-pace{display:none}.selection-card.restricted .capacity-graph{display:block}}"
)


def generate():
    dashboard = json.loads(SRC.read_text())

    # 1. Metadata
    dashboard["uid"] = "ghostship-free-workers"
    dashboard["title"] = "Free models"
    dashboard["description"] = "Free pool generated from Paid models. One selected model per free provider; public tasks only."
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
    panels = []
    for panel in dashboard.get("panels", []):
        if panel.get("id") in {230, 231} or panel.get("repeat") == "orchestrator_model":
            continue
        if panel.get("id") == 233:
            panel["gridPos"].update(x=0, w=24, h=FREE_LANE_HEIGHT)
            options = panel["options"]
            options["content"] = (options["content"]
                .replace('data-lane="worker"', 'data-lane="free"')
                .replace('<b>Workers</b><span>one per provider · ranked by Paced Availability</span>',
                         '<b>Free workers</b><span>one selected model per free provider · public tasks only</span>')
                .replace('</div></section>', BLOCKED_CARD))
            if BLOCKED_CARD not in options["content"]:
                raise ValueError("Paid models worker lane changed: cannot append blocked free providers")
            options["helpers"] += BLOCKED_HELPER
            options["styles"] += FREE_STYLES
            options["defaultContent"] = (
                '<div class="lane"><div class="lane-h"><b>Free workers</b>'
                '<span>No free model selected in the latest snapshot</span></div></div>')
            panel["targets"][0]["expr"] += BLOCKED_QUERY
            panel["description"] = ("Latest snapshot. One selected free model per free provider in collector order; "
                                    "providers with no available model stay as a grey card.")
        if panel.get("id") == 250:
            panel["gridPos"].update(y=FREE_LANE_HEIGHT + 1, h=FREE_QUALITY_HEIGHT)
            panel["options"]["afterRender"] = panel["options"]["afterRender"].replace("?3:15", "?3:7")
            if "?3:7" not in panel["options"]["afterRender"]:
                raise ValueError("Paid models quality pager changed: cannot size the free page")
        panels.append(panel)

    dashboard["panels"] = panels
    for panel in panels:
        if panel.get("type") == "row":
            panel["gridPos"]["y"] = FREE_LANE_HEIGHT + 1 + FREE_QUALITY_HEIGHT
            for index, nested in enumerate(panel.get("panels", [])):
                nested["gridPos"]["y"] = panel["gridPos"]["y"] + 1 + 8 * index
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
