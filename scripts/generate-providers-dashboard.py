#!/usr/bin/env python3
"""Generate the Providers dashboard (ai-usage.json) from modules/self-hosted/siem/dashboard-src/providers.

The panels, queries and Business Text sources are written here; the page's health strip, variables and
evidence row are kept from the committed JSON. Run with --check to verify the committed JSON matches.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'modules/self-hosted/siem/dashboard-src/providers'
PAGE = ROOT / 'modules/self-hosted/siem/dashboards/ai-usage.json'
sys.path.insert(0, str(SRC))
sys.dont_write_bytecode = True
import templates as T

DS = {'type': 'prometheus', 'uid': 'victoriametrics'}
FRESH = 'scalar(max(timestamp(ghostship_ai_collection_duration_seconds))) - 90'


def fresh(sel):
    return f'({sel} and (timestamp({sel}) > {FRESH}))'


def home(expr, flt):
    """OpenCode Free is an instance, not a provider: a route belongs to the provider its model id names
    (google/gemini-3.8-flash is a Google route) and a bare model id is an OpenCode Zen route."""
    if 'provider="opencode-free"' not in flt:
        return expr
    if 'model!~' in flt:
        return 'label_replace(' + expr + ', "provider", "opencode", "model", "[^/]+")'
    return f'label_replace({expr}, "provider", "$1", "model", "([^/]+)/.*")'


def routes(flt):
    parts = []
    for field, metric in (('position', 'position'), ('left', 'remaining_ratio'), ('pace', 'pace_delta'),
                          ('resetAt', 'reset_timestamp_seconds')):
        sel = f'ghostship_ai_picker_model_{metric}{{{flt}}}'
        chosen = f'ghostship_ai_picker_model_selected{{{flt}}} == 1'
        parts.append(home(f'label_replace(({fresh(sel)} and on(category, provider, model, effort) {chosen}), "field", "{field}", "", "")', flt))
    return ('max by (category, provider, model, display_name, effort, state, billing, overspent, pace_state, window, field) (\n '
            + '\n or '.join(parts) + ')')


def account_readings():
    """The account windows a free lane row joins to its route: an account that reads zero is out of quota."""
    account = 'account=~"${free_account:regex}",account!="pi"'
    return '\n or '.join(
        f'label_replace({fresh(f"ghostship_ai_account_window_{metric}{{{account}}}")}, "field", "{field}", "", "")'
        for field, metric in (('acctLeft', 'remaining_ratio'), ('acctReset', 'reset_timestamp_seconds')))


def windows(var, free):
    omit = '' if free else ',account!="openrouter"'
    s = f'account=~"${{{var}:regex}}",account!="pi"{omit}'
    p = f'provider=~"${{{var}:regex}}",provider!="pi"{omit.replace("account", "provider")}'
    lines = []
    for metric, field in (('remaining_ratio', 'left'), ('expected_remaining_ratio', 'expected'),
                          ('reset_timestamp_seconds', 'resetAt'), ('rolling', 'rolling'), ('order', 'order'),
                          ('learning', 'learning'), ('pace_state', 'pace_state')):
        lines.append(f'label_replace({fresh(f"ghostship_ai_account_window_{metric}{{{s}}}")}, "field", "{field}", "", "")')
    lines.append(f'label_replace({fresh(f"ghostship_ai_account_availability{{{s}}}")}, "field", "availability", "", "")')
    head = 'max by (account, kind, quota_id, label, evidence, state, basis, reason, not_used, field) (\n ' + '\n or '.join(lines) + ')'
    tail = [
        f'label_replace({fresh(f"ghostship_ai_account_window_pace_delta_points{{{s}}}")}, "field", "pace_delta", "", "")',
        f'label_replace({fresh(f"ghostship_ai_account_window_missing{{{s}}}")}, "field", "reported_missing", "", "")',
    ]
    if free:
        tail.append(f'label_replace(label_replace({fresh(f"ghostship_ai_provider_free_models{{{p}}}")}, "account", "$1", "provider", "(.+)"), "field", "free_models", "", "")')
        tail.append(f'label_replace(label_replace(count by (provider, reason, obsolete) (ghostship_ai_picker_model_info{{billing=~"free|promotion",category="worker",state!="available",{p}}}), "account", "$1", "provider", "(.+)"), "field", "free_reason", "", "")')
    else:
        tail.append('label_replace(label_replace(ghostship_ai_announced_reset_info{provider="codex"}, "account", "$1", "provider", "(.+)"), "field", "announced", "", "")')
    return head + '\n or ' + '\n or '.join(tail)


def headline_query():
    free = (f'label_replace(label_replace({fresh("ghostship_ai_provider_free_models{provider=~\"${free_account:regex}\",provider!=\"pi\"}")}, '
            '"account", "$1", "provider", "(.+)"), "field", "free_models", "", "")')
    return (routes('category=~"orchestrator|worker",provider!="pi",provider!="opencode-free"') + '\n or ' + windows('paid_account', False) + '\n or ' + free)


def target(expr):
    return [{'refId': 'A', 'datasource': DS, 'expr': expr, 'instant': True, 'range': False, 'format': 'table'}]


def helpers(*files):
    return '\n'.join((SRC / f).read_text() for f in files)


STYLES = (SRC / 'styles.css').read_text()
BASE_HELPERS = ('kit.js', 'routes.js', 'windows.js', 'providers_exports.js')


def panel(pid, grid, description, expr, content, default):
    return {
        'id': pid, 'type': 'marcusolsson-dynamictext-panel', 'title': '', 'datasource': DS,
        'gridPos': grid, 'description': description, 'transparent': True,
        'targets': target(expr),
        'transformations': [{'id': 'organize', 'options': {'excludeByName': {'Time': True}, 'renameByName': {'Value': 'value'}, 'indexByName': {}}}],
        'fieldConfig': {'defaults': {}, 'overrides': []},
        'options': {'editor': {'format': 'none', 'language': 'handlebars'}, 'editors': [], 'externalStyles': [], 'contentPartials': [],
                    'renderMode': 'allRows', 'status': '', 'wrap': True, 'styles': STYLES, 'content': content,
                    'helpers': helpers(*BASE_HELPERS), 'defaultContent': default, 'afterRender': ''},
    }


EMPTY = '<div class="gx"><div class="in"><header><b>%s</b><span>No readings in the latest snapshot · check the collector</span></header></div></div>'


def build():
    page = json.loads(PAGE.read_text())
    by_id = {p['id']: p for p in page['panels']}
    health = by_id[201]
    evidence = by_id[240]
    # Sized to the taller of the desktop and the 390 px phone reading of the live data, so no panel scrolls.
    TILES = 9
    TOP = 2 + TILES
    LH = 16
    LISTS = 19
    # Two columns of about equal height: the lanes on the left, the provider lists on the right.
    LHF = 11
    LISTF = 8
    # OpenCode Free is the free pool of the OpenCode catalog; the collector maps it to the T3 scope and
    # publishes its billing as unknown, so the variables move it from the paid list to the free list.
    for variable in page['templating']['list']:
        if variable['name'] == 'paid_account':
            old, new = 'scope="t3",account!="openrouter"', 'scope="t3",account!="opencode-free",account!="openrouter"'
            for key in ('query', 'definition'):
                text = variable['query']['query'] if key == 'query' else variable['definition']
                text = text if new in text else text.replace(old, new)
                assert new in text
                if key == 'query':
                    variable['query']['query'] = text
                else:
                    variable['definition'] = text
        if variable['name'] == 'free_account':
            # Only a provider with an owner-approved free worker is listed; the public pool is counted on the Free models page.
            selector = 'ghostship_ai_account_card_order{scope="free",account!="pi"}'
            approved = ('label_replace(max by (provider) (ghostship_ai_picker_model_approved_free{category="worker",provider!="opencode-free"} == 1), "account", "$1", "provider", "(.+)") '
                        'or label_replace(max by (provider) (label_replace(label_replace(ghostship_ai_picker_model_approved_free{category="worker",provider="opencode-free"} == 1, '
                        '"provider", "$1", "model", "([^/]+)/.*"), "provider", "opencode", "model", "[^/]+")), "account", "$1", "provider", "(.+)")')
            query = ('query_result(sort(%s and on(account) (%s) and (timestamp(%s) > scalar(max(timestamp(ghostship_ai_collection_duration_seconds))) - 90)))' % (selector, approved, selector))
            variable['query']['query'] = query
            variable['definition'] = query
    marker = "info.reason === 'unsupported' ? ' · #470'"
    if marker not in health['options']['helpers']:
        health['options']['helpers'] = health['options']['helpers'].replace(
            "'unavailable · ' + (info.reason || info.status)}",
            "'unavailable · ' + (info.reason || info.status) + (source === 't3' && info.reason === 'unsupported' ? ' · #470' : '')}")
    assert marker in health['options']['helpers']
    health['gridPos']['h'] = 2
    panels = [health]
    panels.append(panel(260, {'x': 0, 'y': 2, 'w': 24, 'h': TILES},
        'Who gets the next job, and what is out, overspent or unknown. Built from the latest snapshot only.',
        headline_query(), T.HEADLINE, EMPTY % 'Summary'))
    panels.append(panel(261, {'x': 0, 'y': TOP, 'w': 12, 'h': LH}, 'Orchestrator and paid worker routes, one per provider, in the order the picker ranks them.',
        routes('category="orchestrator",provider!="pi"') + '\n or ' + routes('category="worker",billing!~"free|promotion",provider!="pi",provider!="opencode-free"'),
        T.lane(('orchestrator', 'Orchestrators', 'pick order · bar is Paced Availability', 0, 'No orchestrator route in the latest snapshot'),
               ('paid', 'Paid workers', 'pick order · bar is Paced Availability', 0, 'No paid worker route in the latest snapshot')), EMPTY % 'Paid tiers'))
    panels.append(panel(262, {'x': 0, 'y': TOP + LH, 'w': 12, 'h': LHF}, 'Free worker routes, one per provider, in the order the picker ranks them; the top ten are shown.',
        # Only the owner-approved free workers are listed; OpenCode Free routes are filed under their provider.
        routes('category="worker",billing=~"free|promotion",provider!="pi",provider!="opencode-free",approved_free="true"')
        + '\n or ' + routes('category="worker",provider="opencode-free",model=~".+/.*",approved_free="true"')
        + '\n or ' + routes('category="worker",provider="opencode-free",model!~".*/.*",approved_free="true"')
        + '\n or ' + account_readings(),
        T.lane(('free', 'Free workers', 'pick order · hatched means no limit seen, not 100% (filled by #467)', 10, 'No free worker route in the latest snapshot')), EMPTY % 'Free workers'))
    panels.append(panel(264, {'x': 12, 'y': TOP, 'w': 12, 'h': LISTS}, 'Account windows of the paid providers: the lowest known window leads.',
        windows('paid_account', False), T.PAID, EMPTY % 'Paid providers'))
    panels.append(panel(265, {'x': 12, 'y': TOP + LISTS, 'w': 12, 'h': LISTF}, 'Free providers: blocked ones first. A free provider with no limit seen is unknown, not 100%.',
        windows('free_account', True), T.FREE, EMPTY % 'Free providers'))
    evidence['gridPos']['y'] = TOP + max(LH + LHF, LISTS + LISTF)
    evidence['title'] = 'Evidence tables'
    for i, nested in enumerate(evidence['panels']):
        nested['gridPos']['y'] = evidence['gridPos']['y'] + 1 + 8 * i
    panels.append(evidence)
    page['panels'] = panels
    page['description'] = 'Providers: who gets the next job, which allowances are out, overspent or unknown, and when they return.'
    return page


if __name__ == '__main__':
    text = json.dumps(build(), indent=2) + '\n'
    if sys.argv[1:] == ['--check']:
        if PAGE.read_text() != text:
            sys.exit('ai-usage.json does not match the generator; run scripts/generate-providers-dashboard.py')
        print('OK: ai-usage.json matches the generator')
    else:
        PAGE.write_text(text)
        print('wrote', PAGE.relative_to(ROOT))
