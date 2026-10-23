#!/usr/bin/env python3
"""Generate the Free models and providers dashboard from ai-usage.json.

The free dashboard mirrors the Providers and model decisions page (ai-usage.json)
for the free pool:
- Swaps selector filters:
  picker_eligible="true",provider!="openrouter" -> billing=~"free|promotion"
  scope="t3",account!="openrouter" -> scope="free"
- Drops paid-only panels (orchestrators text & dynamictext)
- Drops paid-only variables (orchestrator_model)
- Updates metadata (uid="ghostship-free-workers", title="Free models and providers")
- Re-layouts vertical positions without gaps

Usage:
  python3 scripts/generate-free-workers-dashboard.py          # Regenerates free-workers.json
  python3 scripts/generate-free-workers-dashboard.py --check  # Fails if committed file differs
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "modules/self-hosted/siem/dashboards/ai-usage.json"
DST = ROOT / "modules/self-hosted/siem/dashboards/free-workers.json"


def generate():
    dashboard = json.loads(SRC.read_text())

    # 1. Metadata
    dashboard["uid"] = "ghostship-free-workers"
    dashboard["title"] = "Free models and providers"
    dashboard["description"] = "Free pool mirror of the Providers and models dashboard"
    dashboard["links"] = [
        {
            "title": "Providers",
            "type": "link",
            "url": "/d/ghostship-ai-usage",
            "targetBlank": False,
        }
    ]

    # 2. Templating variables
    variables = []
    for v in dashboard.get("templating", {}).get("list", []):
        if v.get("name") == "orchestrator_model":
            continue
        raw = json.dumps(v)
        raw = raw.replace('picker_eligible=\\"true\\",provider!=\\"openrouter\\"', 'billing=~\\"free|promotion\\"')
        raw = raw.replace('picker_eligible=\\"true\\",provider=~\\"$provider\\",provider!=\\"openrouter\\"', 'billing=~\\"free|promotion\\",provider=~\\"$provider\\"')
        raw = raw.replace('scope=\\"t3\\",account!=\\"openrouter\\"', 'scope=\\"free\\"')
        variables.append(json.loads(raw))
    dashboard["templating"]["list"] = variables

    # 3. Panels
    panels = []
    paid_panel_ids = {230, 231}
    current_y = 0

    for p in dashboard.get("panels", []):
        if p.get("id") in paid_panel_ids or p.get("repeat") == "orchestrator_model":
            continue

        raw = json.dumps(p)
        raw = raw.replace('picker_eligible=\\"true\\",provider!=\\"openrouter\\"', 'billing=~\\"free|promotion\\"')
        raw = raw.replace('picker_eligible=\\"true\\",provider=~\\"$provider\\",provider!=\\"openrouter\\"', 'billing=~\\"free|promotion\\",provider=~\\"$provider\\"')
        raw = raw.replace('scope=\\"t3\\",account!=\\"openrouter\\"', 'scope=\\"free\\"')
        panel = json.loads(raw)

        if panel.get("id") == 200:
            panel["options"]["content"] = (
                '<div style="font-family:Inter,system-ui,sans-serif;max-width:100%;overflow-wrap:anywhere">'
                '<strong>Free models and providers</strong>'
                '<span style="font-size:11px;color:#8b8f99"> · Free worker pool and free provider accounts · Public tasks only</span>'
                '</div>'
            )
        elif panel.get("id") == 232:
            panel["options"]["content"] = (
                '<div style="font-family:Inter,system-ui,sans-serif;max-width:100%;overflow-wrap:anywhere">'
                '<strong>Free worker models</strong>'
                '<span style="font-size:11px;color:#8b8f99"> · Public-only policy · Exhausted routes greyed out · Dynamic ordering by capacity</span>'
                '</div>'
            )
        elif panel.get("id") == 234:
            panel["options"]["content"] = (
                '<div style="font-family:Inter,system-ui,sans-serif;max-width:100%;overflow-wrap:anywhere">'
                '<strong>Free provider capacity</strong>'
                '<span style="font-size:11px;color:#8b8f99"> · Short windows are blue above zero. Only weekly/monthly windows are paced.</span>'
                '</div>'
            )

        if "gridPos" in panel:
            panel["gridPos"]["y"] = current_y
            current_y += panel["gridPos"]["h"]

        panels.append(panel)

    dashboard["panels"] = panels
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
