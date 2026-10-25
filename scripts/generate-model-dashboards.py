#!/usr/bin/env python3
"""Generate the Paid models and Free models dashboards from one source.

The two pages share their panels: a summary band, the provider lane with the
selected route of each provider and why its other routes are skipped, and the
reason list. Only the scope selector differs. The helpers, styles and frozen
evidence panels live in modules/self-hosted/siem/dashboard-src/models.

Usage: python3 scripts/generate-model-dashboards.py [--check]
"""

import argparse
import copy
import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "modules/self-hosted/siem/dashboard-src/models"
OUT = ROOT / "modules/self-hosted/siem/dashboards"
DS = {"type": "prometheus", "uid": "victoriametrics"}
FRESH = "scalar(max(timestamp(ghostship_ai_collection_duration_seconds))) - 90"
SELECTED_JOIN = "on(category, provider, model, effort)"

# The scope of a page: the selector that picks its routes.
SCOPES = {
    "paid": {
        "uid": "ghostship-paid-models",
        "title": "Paid models",
        "description": "Paid and subscription routes: which is picked next, and why every other route is or is not picked.",
        # A pruned (obsolete) route is published with picker_eligible="false", so the paid scope is
        # the billing class, not eligibility: every non-free route of the paid providers.
        "routes": ['billing!~"free|promotion",provider!="openrouter",provider!="pi",provider!="opencode-free",provider=~"$provider"'],
        "variable": 'label_values(ghostship_ai_picker_model_info{billing!~"free|promotion",provider!="openrouter",provider!="pi",provider!="opencode-free"}, provider)',
        "regex": "",
        "lane_extra": "",
        "categories": ("orchestrator", "worker"),
    },
    "free": {
        "uid": "ghostship-free-workers",
        "title": "Free models",
        "description": "Free routes: which is picked next, and why every other route is or is not picked. Public tasks only.",
        # OpenCode Free is an instance of the OpenCode catalog and its billing is published as unknown, so the
        # free scope names it beside the free and promotion billing; its routes are filed by their model id.
        "routes": ['billing=~"free|promotion",provider!="pi",provider!="opencode-free",provider=~"$provider"',
                   'provider="opencode-free",model=~"$provider/.*"',
                   'provider="opencode-free",model!~".*/.*"'],
        # Only the owner-approved free workers are lane rows; the rest of the public pool is counted, never listed.
        "lane_extra": ',approved_free="true"',
        "variable": 'query_result(count by (provider) (ghostship_ai_picker_model_info{billing=~"free|promotion",provider!="pi",provider!="opencode-free"}))',
        "regex": '/provider="([^"]+)"/',
        "categories": ("worker",),
    },
}

# The evidence panels were written for the paid scope; this is how each of their
# selectors reads for the free scope.
SUBSTITUTIONS = (
    ('picker_eligible="true",provider!="openrouter"', 'billing=~"free|promotion"'),
    ('billing!~"free|promotion"', 'billing=~"free|promotion"'),
    (',provider!="pi"', ''),
    (',provider!="openrouter"', ''),
)


def read(name):
    return (SRC / name).read_text()


def read_json(name):
    return json.loads(read(name))


def fresh(selector):
    return f"({selector} and (timestamp({selector}) > {FRESH}))"


def home(expr, flt):
    """OpenCode Free is an instance, not a provider: a route belongs to the provider its model id names
    (google/gemini-3.8-flash is a Google route) and a bare model id is an OpenCode Zen route."""
    if 'provider="opencode-free"' not in flt:
        return expr
    if "model!~" in flt:
        # Bare model ids are Zen routes: they follow the provider filter through the Zen provider.
        return (f'(label_replace({expr}, "provider", "opencode", "model", "[^/]+") and on() '
                'ghostship_ai_picker_model_info{provider="opencode",provider=~"$provider"})')
    return f'label_replace({expr}, "provider", "$1", "model", "([^/]+)/.*")'


def routes(flt):
    """The selected route of every provider, one row per number."""
    parts = []
    for field, metric in (("position", "position"), ("left", "remaining_ratio"), ("pace", "pace_delta"),
                          ("resetAt", "reset_timestamp_seconds")):
        selector = f"ghostship_ai_picker_model_{metric}{{{flt}}}"
        chosen = f"ghostship_ai_picker_model_selected{{{flt}}} == 1"
        parts.append(home(f'label_replace(({fresh(selector)} and {SELECTED_JOIN} {chosen}), "field", "{field}", "", "")', flt))
    return ("max by (category, provider, model, display_name, effort, state, trust, billing, overspent, pace_state, "
            "window, sensitivity_sensitive, approved_free, field) (\n " + "\n or ".join(parts) + ")")


def census(flt):
    """Every candidate route, counted by the labels that decide why it is or is not picked."""
    position = home(fresh(f"ghostship_ai_picker_model_position{{{flt}}}"), flt)
    # A route whose pick text changed between two collections is published twice inside the freshness window;
    # the inner max counts it once.
    group = ("category, provider, pool, state, trust, overspent, pace_state, sensitivity_sensitive, "
             "billing, approved_free, obsolete, reason")
    return (f'label_replace(count by ({group}) (max by (model, effort, {group}) '
            f'(label_replace({position}, "reason", "pick", "reason", "pick: .*"))), "field", "census", "", "")')


def filters(scope, category):
    return [f'category="{category}",{route}' for route in SCOPES[scope]["routes"]]


def joined_readings():
    """The readings a free lane row joins to its route: the account's windows and the route's calibration."""
    account = 'account=~"$provider"'
    parts = []
    for field, metric in (("acctLeft", "remaining_ratio"), ("acctReset", "reset_timestamp_seconds")):
        parts.append(f'label_replace({fresh(f"ghostship_ai_account_window_{metric}{{{account}}}")}, "field", "{field}", "", "")')
    parts.append(f'label_replace({fresh("ghostship_ai_free_route_calibration_state{provider=~\"$provider\"}")}, "field", "calibration", "", "")')
    return "\n or ".join(parts)


def lane_query(scope, categories=None):
    parts = []
    for category in categories or SCOPES[scope]["categories"]:
        for selector in filters(scope, category):
            parts += [routes(selector + SCOPES[scope]["lane_extra"]), census(selector)]
    if scope == "free":
        parts.append(joined_readings())
    return "\n or ".join(parts)


def census_query(scope):
    return "\n or ".join(census(selector) for category in SCOPES[scope]["categories"]
                         for selector in filters(scope, category))


def reasons_query(scope):
    """The reasons count the same routes as the summary: it needs the orchestrator positions to drop the orchestrators
    the picker does not use, or the two panels disagree by those routes."""
    parts = [census_query(scope)]
    if "orchestrator" in SCOPES[scope]["categories"]:
        parts.append(lane_query(scope, ("orchestrator",)))
    return "\n or ".join(parts)


def target(expr):
    return [{"refId": "A", "datasource": DS, "expr": expr, "instant": True, "range": False, "format": "table"}]


def helpers():
    return "\n".join(read(name) for name in ("kit.js", "routes.js", "census.js", "models.js"))


def tile_pick(key, title, none, width):
    return (
        '{{#if %(k)s}}{{#with %(k)s}}<div class="tile %(w)s {{kind}}" data-tile="%(k)s"><span class="k">%(t)s</span>'
        '<span class="v"><span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span>{{name}}</span>'
        '<span class="s" title="{{model}}">{{model}}{{#if detail}} · {{detail}}{{/if}}</span></div>{{/with}}'
        '{{else}}<div class="tile %(w)s unk" data-tile="%(k)s"><span class="k">%(t)s</span>'
        '<span class="v">None available</span><span class="s">%(n)s</span></div>{{/if}}'
    ) % {"k": key, "t": title, "n": none, "w": width}


def summary_template(scope):
    picks = ""
    if scope == "paid":
        picks += tile_pick("orchestrator", "Next orchestrator", "every orchestrator is out or held", "pick")
    picks += tile_pick("worker", "Next paid worker" if scope == "paid" else "Next free worker",
                       "every worker route is out or held", "pick" if scope == "paid" else "wide")
    stat = "stat half"
    return (
        '{{#with (modelSummary data (variable "__to") "%s")}}<div class="gx"><div class="tiles">' % scope + picks +
        '<div class="tile %s good" data-tile="pickable"><span class="k">Pickable</span><span class="v">{{pickable.count}}'
        ' <small>of {{pickable.of}} routes</small></span><span class="s">available and not overspent</span></div>' % stat +
        '<div class="tile %s{{#if skipped.count}} bad{{else}} zero{{/if}}" data-tile="skipped"><span class="k">Skipped</span>'
        '<span class="v">{{skipped.count}}</span><span class="s" title="{{skipped.text}}">{{#if skipped.text}}{{skipped.text}}{{else}}none{{/if}}</span></div>' % stat +
        '</div></div>{{/with}}'
    )


def lane_section(key, title, sub, limit, empty):
    return (
        '{{#with (modelRows data (variable "__to") "@KEY@" @LIMIT@)}}<div class="ls" data-lane="@KEY@">'
        '<header><b>@TITLE@</b><span>@SUB@</span></header>'
        '{{#if rows.length}}<ol>{{#each rows}}<li class="r {{kind}}{{#if first}} first{{/if}}{{#if next}} next{{/if}}" data-provider="{{provider}}" data-rank="{{rank}}">'
        '<div class="rw"><span class="n">{{rank}}</span><span class="ic" style="background:{{bg}};color:{{fg}}">{{icon}}</span>'
        '<div class="bd"><div class="l1"><b class="nm">{{name}}</b>{{#if next}}<em class="pill good">Next</em>{{/if}}'
        '{{#if word}}<em class="pill {{kind}}">{{word}}</em>{{/if}}'
        '<span class="md" title="{{model}}">{{model}}</span>{{#if calib}}<span class="cal {{calib.tone}}" title="{{calib.hint}} (#462)">{{calib.word}}</span>{{/if}}{{#if (eq kind "unk")}}{{#unless noRoute}}<span class="pa unk"></span>{{/unless}}{{/if}}'
        '{{#if capacity}}<span class="big {{#if leftText}}{{kind}}{{else}}unk{{/if}}">{{capacity}}</span>{{/if}}</div>'
        '{{#if acctNote}}<div class="l2"><span class="pt">{{acctNote}}</span>{{#if when}}<span class="wn"><span class="sw">{{word}} · </span>{{when}}</span>{{/if}}</div>{{/if}}'
        '{{#if pace}}<div class="l2">{{#if paceLong}}<span class="pa {{#if paKnown}}{{paSide}}{{else}}unk{{/if}}">{{#if paKnown}}'
        '<i style="left:{{paLeft}}%;width:{{paWidth}}%"></i>{{/if}}</span>'
        '<span class="pt">{{#if paKnown}}<span class="pv">{{paText}}</span> <span class="long">Paced Availability</span>'
        '{{else}}<span class="pv unk">{{#if out}}no pace while out{{else}}pace unknown{{/if}}</span>{{/if}}</span>'
        '{{else}}<span class="pt"></span>{{/if}}'
        '{{#if when}}<span class="wn"><span class="sw">{{word}}{{#if word}} · {{/if}}</span>{{when}}</span>{{/if}}</div>{{/if}}'
        '{{#if many}}<div class="l3"><span class="cb">{{#each census.parts}}<i class="{{tone}}" style="width:{{pct}}%" '
        'title="{{count}} {{label}}"></i>{{/each}}</span><span class="ct">{{census.text}}</span></div>'
        '{{#if census.skipped}}<div class="cs">{{census.skipped}}{{#if census.partial}} · <span class="lm">'
        '{{census.limited}} not for sensitive work</span>{{/if}}</div>{{/if}}{{/if}}'
        '</div></div></li>{{/each}}</ol>{{#if more}}<div class="more">+ {{more}} more providers</div>{{/if}}'
        '{{else}}<div class="none">@EMPTY@</div>{{/if}}</div>{{/with}}'
    ).replace("@KEY@", key).replace("@LIMIT@", str(limit)).replace("@TITLE@", title).replace("@SUB@", sub).replace("@EMPTY@", empty)


def lane_template(scope, which="workers"):
    note = "the number is the picker's own order · bar is Paced Availability · bottom bar counts every route"
    if which == "orchestrator":
        sections = lane_section("orchestrator", "Orchestrator", "the picker's first orchestrator · bar is Paced Availability", 0, "No orchestrator route in the latest snapshot")
    elif scope == "paid":
        sections = lane_section("paid", "Paid workers", note + " · free routes are tried first", 0, "No paid worker route in the latest snapshot")
    else:
        sections = lane_section("free", "Free workers", "the owner-approved free workers, in the picker's own order · bar is Paced Availability · hatched means no limit seen yet (filled by #467) · public tasks only", 0, "No free worker route in the latest snapshot")
    return '<section class="gx"><div class="in lane">' + sections + "</div></section>"


REASONS_TEMPLATE = (
    '<section class="gx"><div class="in why"><header><b>Why routes are picked or skipped</b>'
    '<span>every candidate route is counted once</span></header>'
    '{{#with (modelReasons data)}}{{#if empty}}<div class="none">No routes in the latest snapshot</div>{{else}}'
    '<ol>{{#each list}}<li class="w {{tone}}" data-reason="{{key}}"><div class="t"><span class="nm">{{label}}</span>'
    '<span class="ct">{{count}}</span></div><div class="bar"><i class="{{tone}}" style="width:{{width}}%"></i></div>'
    '<div class="hn"><b>{{hint}}</b>{{#if who}} · {{who}}{{/if}}</div></li>{{/each}}'
    '<li class="w nodata" data-reason="tool-loop-proof"><div class="t"><span class="nm">No tool-loop proof</span>'
    '<span class="ct">not reported yet · #479</span></div><div class="bar hatch"></div>'
    '<div class="hn">the collector publishes no per-route tool-loop proof, so no count is drawn</div></li></ol>'
    '<div class="ft"><b>{{limited}}</b> routes are not for sensitive work</div>{{/if}}{{/with}}</div></section>'
)


def empty(title):
    return ('<div class="gx"><div class="in"><header><b>%s</b><span>No readings in the latest snapshot · '
            'check the collector</span></header></div></div>' % title)


def dynamic(pid, grid, description, expr, content, default, styles):
    return {
        "id": pid, "type": "marcusolsson-dynamictext-panel", "title": "", "datasource": DS, "gridPos": grid,
        "description": description, "transparent": True, "targets": target(expr),
        "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True},
                                                            "renameByName": {"Value": "value"}, "indexByName": {}}}],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {"editor": {"format": "none", "language": "handlebars"}, "editors": [], "externalStyles": [],
                    "contentPartials": [], "renderMode": "allRows", "status": "", "wrap": True, "styles": styles,
                    "content": content, "helpers": helpers(), "defaultContent": default, "afterRender": ""},
    }


def routes_table(scope, y):
    selectors = [f'category=~"orchestrator|worker",{route}' for route in SCOPES[scope]["routes"]]
    return {
        "id": 270, "type": "table", "title": "Every route and why it is or is not picked", "datasource": DS,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 14},
        "description": "One row per candidate route: its state, trust, spend flags and the collector's reason. "
                       "The value is the picker position.",
        "targets": target("\n or ".join(f"ghostship_ai_picker_model_position{{{selector}}}" for selector in selectors)),
        "transformations": [{"id": "organize", "options": {
            "excludeByName": {"Time": True, "__name__": True, "job": True, "instance": True, "picker_eligible": True,
                              "pool": True, "pool_label": True, "approved_free": True, "binding_window": True,
                              "quota_id": True, "reset_source": True, "pick_basis": True, "pick_reason": True,
                              "model": True, "allowance_basis": True, "allowance_plan": True, "data_policy": True,
                              "sensitive_ok": True, "sensitivity_public": True, "sensitivity_internal": True,
                              "quality_basis": True},
            "renameByName": {"category": "Role", "provider": "Provider", "display_name": "Model", "effort": "Effort",
                             "state": "State", "trust": "Trust", "billing": "Billing", "overspent": "Overspent",
                             "pace_state": "Pace", "window": "Window", "sensitivity_sensitive": "Sensitive work",
                             "reason": "Reason", "Value": "Position"},
            "indexByName": {"category": 0, "provider": 1, "display_name": 2, "effort": 3, "state": 4, "overspent": 5,
                            "trust": 6, "sensitivity_sensitive": 7, "reason": 8, "Value": 9}}},
            {"id": "sortBy", "options": {"sort": [{"field": "Position", "desc": False}]}}],
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}}, "overrides": []},
        "options": {"showHeader": True, "cellHeight": "sm", "enablePagination": True, "footer": {"show": False}},
    }


def evidence_panels(scope):
    panels = copy.deepcopy(read_json("evidence.json"))
    if scope == "free":
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

        panels = visit(panels)
        for old, count in counts.items():
            if count == 0:
                raise ValueError(f"Paid evidence selector changed or disappeared: {old}")
        raw = json.dumps(panels)
        for forbidden in ('picker_eligible=\\"true\\"', 'scope=\\"t3\\"', "orchestrator_model", "subscription"):
            if forbidden in raw:
                raise ValueError(f"Paid selector remains in the free dashboard: {forbidden}")
    return panels


# Panel heights in grid rows (30 px plus 8 px between rows), each the least that holds the live reading at
# both 1600 px and 390 px, so no panel scrolls.
TILES_HEIGHT = {"paid": 7, "free": 7}
ORCHESTRATOR_HEIGHT = 5
LANE_HEIGHT = {"paid": 23, "free": 20}
REASONS_HEIGHT = {"paid": 22, "free": 22}


def build(scope):
    spec = SCOPES[scope]
    styles = read("styles.css")
    dashboard = copy.deepcopy(read_json("base.json"))
    dashboard["uid"] = spec["uid"]
    dashboard["title"] = spec["title"]
    dashboard["description"] = spec["description"]
    dashboard["version"] = 8
    dashboard["links"] = [{"title": title, "type": "link", "url": "/d/" + uid, "targetBlank": False}
                          for title, uid in (("Providers", "ghostship-ai-usage"), ("Paid models", "ghostship-paid-models"),
                                             ("Free models", "ghostship-free-workers"))]
    variable = {
        "name": "provider", "label": "Provider", "type": "query", "datasource": DS,
        "query": {"query": spec["variable"], "refId": "StandardVariableQuery"},
        "refresh": 1, "multi": True, "includeAll": True, "allValue": ".*", "current": {"text": "All", "value": "$__all"},
        "options": [], "hide": 0, "skipUrlSync": False, "definition": spec["variable"], "regex": spec["regex"], "sort": 1,
    }
    dashboard["templating"] = {"list": [variable]}
    strip = read_json("strip.json")
    # Sized to the taller of the desktop and the 390 px phone reading of the live lists, so no panel scrolls.
    # The paid orchestrator is one row across the page; the worker lane and the reasons list share the next row.
    top = 2 + TILES_HEIGHT[scope]
    panels = [strip,
              dynamic(260, {"x": 0, "y": 2, "w": 24, "h": TILES_HEIGHT[scope]}, "What is picked next, how many routes are pickable and how many are skipped.",
                      census_query(scope) + "\n or " + lane_query(scope), summary_template(scope), empty("Summary"), styles)]
    if scope == "paid":
        panels.append(dynamic(263, {"x": 0, "y": top, "w": 24, "h": ORCHESTRATOR_HEIGHT},
                              "The orchestrator route in the picker's order, with Paced Availability and a bar that counts every "
                              "route of the provider by the reason it is or is not picked.",
                              lane_query(scope, ("orchestrator",)), lane_template(scope, "orchestrator"), empty("Orchestrator"), styles))
        top += ORCHESTRATOR_HEIGHT
    workers = ("worker",)
    # The lane and the reasons list share one row, so they are one height; the taller reading sets it.
    lane_height = max(LANE_HEIGHT[scope], REASONS_HEIGHT[scope])
    panels += [dynamic(261, {"x": 0, "y": top, "w": 15, "h": lane_height},
                       "The selected route of every provider in the picker's order, with Paced Availability and a bar that "
                       "counts every route of the provider by the reason it is or is not picked.",
                       lane_query(scope, workers), lane_template(scope), empty(spec["title"]), styles),
               dynamic(262, {"x": 15, "y": top, "w": 9, "h": lane_height},
                       "Every candidate route counted once by the reason it is or is not picked.",
                       reasons_query(scope), REASONS_TEMPLATE, empty("Reasons"), styles)]
    y = top + max(lane_height, REASONS_HEIGHT[scope])
    evidence = evidence_panels(scope)
    nested = [routes_table(scope, y + 1), evidence["250"], evidence["241"], evidence["242"]]
    offset = y + 1
    for panel in nested:
        panel["gridPos"] = {"x": 0, "y": offset, "w": 24, "h": {270: 14, 250: 14}.get(panel["id"], 8)}
        offset += panel["gridPos"]["h"]
    panels.append({"id": 240, "type": "row", "title": "Evidence tables",
                   "collapsed": True, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": nested})
    dashboard["panels"] = panels
    return json.dumps(dashboard, indent=2) + "\n"


FILES = {"paid": OUT / "paid-models.json", "free": OUT / "free-workers.json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if a committed dashboard differs from the generator")
    args = parser.parse_args()
    failed = False
    for scope, path in FILES.items():
        generated = build(scope)
        if not args.check:
            path.write_text(generated)
            print(f"Wrote {path}")
            continue
        committed = path.read_text() if path.exists() else ""
        if committed != generated:
            failed = True
            diff = "".join(difflib.unified_diff(committed.splitlines(keepends=True), generated.splitlines(keepends=True),
                                                fromfile="committed", tofile="generated"))
            print(f"Error: {path} differs from generator output:\n{diff[:4000]}", file=sys.stderr)
            print("Run: python3 scripts/generate-model-dashboards.py", file=sys.stderr)
    if args.check:
        if failed:
            sys.exit(1)
        print("OK: paid-models.json and free-workers.json match the generator")


if __name__ == "__main__":
    main()
