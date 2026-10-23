"""The Providers page of the AI usage dashboard.

The page is six sections, each one a Business Text panel, and the evidence
below them in collapsed rows. The tests here pin the contract the page has
with the owner: the order of a tier is the collector's own winner position,
the fill of a bar is the share left now, the line in the bar is the share the
window expects to be left now, and the pace reads the difference between the
two.

The page opens with the capacity cards: one card per account, one row per
window of the account, and the accounts that publish no window of their own
as a chip. The numbers of a card are the collector's account window gauges,
and the card order, the names and the icons are the presentation the owner
approved.

The queries are executed against the committed review fixture, so the worked
cases are the numbers the store returns and not a copy of them.
"""
import json
import math
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "modules/self-hosted/siem/dashboards/ai-usage.json"
FIXTURE = ROOT / "tests/fixtures/ai-usage/providers-review.prom"
FIXTURE_ROUTING_ON = ROOT / "tests/fixtures/ai-usage/providers-review-routing-on.prom"

# The sections of the page, in the order the owner approved.
SECTIONS = ("Provider capacity", "Model selection", "Bulk", "Free", "Frontier", "3D")
TIERS = {"Bulk": "bulk", "Free": "free", "Frontier": "frontier", "3D": "3d"}

# The account window gauges of the collector, and the field of a row each of
# them fills. The panel reads them all in one query, and the field says
# which one a row holds.
CAPACITY_METRICS = {
    "ghostship_ai_account_window_remaining_ratio": "left",
    "ghostship_ai_account_window_expected_remaining_ratio": "expected",
    "ghostship_ai_account_window_reset_timestamp_seconds": "resetAt",
    "ghostship_ai_account_window_check_timestamp_seconds": "checked",
    "ghostship_ai_account_window_rolling": "rolling",
    "ghostship_ai_account_window_order": "order",
    "ghostship_ai_account_window_learning": "learning",
    # The free models of a provider, apart from its paid allowance.
    "ghostship_ai_provider_free_models": "free_models",
}

# The content of the panel with the fixture, measured in Playwright at the
# production font (Inter), with the panel's own styles and a phone of 390 px
# and a desktop of 1600 px. A grid row of the dashboard is 37 px, so the
# panel is tall enough for the taller of the two readings.
#
# The free line of a card is part of the measurement: four cards of the live
# set hold free models, and the line adds 84 px at 390 px.
CAPACITY_PHONE_HEIGHT = 1798
CAPACITY_DESKTOP_HEIGHT = 538
CAPACITY_ROW_HEIGHT = 37

# The content of the model selection panel, measured in Playwright the same
# way with the headroom the panel is sized for: the five static rows, the
# Free divider, and twenty free providers. The live set holds sixteen.
SELECTION_PHONE_HEIGHT = 883
SELECTION_DESKTOP_HEIGHT = 861

# The moment the fixture was read. The resets of the fixture are counted
# from it, so the worked cases are the rows of that moment.
CAPACITY_NOW = int(
    datetime(2026, 10, 22, 21, 1, 17, tzinfo=timezone.utc).timestamp() * 1000
)

# The name a provider is read by, as the mockup reads it. A provider that
# is not named here keeps the identifier the collector publishes.
PROVIDER_NAMES = {
    "claude": "Claude",
    "codex": "Codex",
    "antigravity": "Antigravity",
    "opencode-go": "OpenCode Go",
    "opencode": "OpenCode",
    "ollama": "Ollama",
    "grok": "Grok",
    "groq": "Groq",
    "nvidia": "NVIDIA",
    "google": "Google",
    "openrouter": "OpenRouter",
    "cursor": "Cursor",
    "kilo": "Kilo",
    "kilo-keyed": "Kilo (keyed)",
    "cloudflare-workers-ai": "Cloudflare",
    "requesty": "Requesty",
    "upstage": "Upstage",
    "inception": "Inception",
    "ovh": "OVH",
    "deepseek": "DeepSeek",
    "moonshot": "Moonshot",
}


def panels(page):
    """The panels of the page, with the ones a collapsed row holds."""
    out = []

    def walk(items, collapsed):
        for panel in items:
            out.append((panel, collapsed))
            if panel.get("type") == "row":
                walk(panel.get("panels") or [], bool(panel.get("collapsed")))

    walk(page["panels"], False)
    return out


def section(page, title):
    """The panel of a section, by its title."""
    for panel, _ in panels(page):
        if panel.get("title", "").startswith(title):
            return panel
    raise AssertionError(f"the page has no section {title!r}")


def expressions(panel):
    return " ".join(target.get("expr") or "" for target in panel.get("targets") or [])


def find_target(panel, needle):
    """The target whose expression names the metric."""
    for target in panel.get("targets") or []:
        if needle in (target.get("expr") or ""):
            return target
    raise AssertionError(f"no target of {panel.get('title')!r} names {needle!r}")


def target_by_field(panel, field):
    """The target that carries a named field of the row."""
    organize = next(
        transformation
        for transformation in panel.get("transformations") or []
        if transformation["id"] == "organize"
    )
    rename = organize["options"]["renameByName"]
    for reference, name in rename.items():
        if name != field:
            continue
        ref_id = reference.split("#")[-1]
        for target in panel.get("targets") or []:
            if target.get("refId") == ref_id:
                return target
    raise AssertionError(
        f"no target of {panel.get('title')!r} carries the field {field!r}"
    )


def inner(expression):
    """The expression of a target without the aggregation around it."""
    match = re.match(r"^max by \([^)]*\) \((.*)\)$", expression or "", re.S)
    return match.group(1) if match else expression


def cells(fragment):
    """The classes of the cells of a table row."""
    return [
        (match.group(1) or "").strip()
        for match in re.finditer(r'<(?:th|td)(?:\s+class="([^"]*)")?', fragment)
    ]


def table_columns(content):
    """The header cells of a table and the cells of its first row."""
    head = re.search(r"<thead>(.*?)</thead>", content, re.S)
    row = re.search(r"<tbody>(.*?)</tr>", content, re.S)
    assert head and row, "the panel has no table"
    return cells(head.group(1)), cells(row.group(1))


def hide_marker(classes):
    """The classes that hide a column on a narrow screen."""
    return tuple(sorted(name for name in classes.split() if name.startswith("hide")))


def media_body(styles):
    """The rules of the narrow screen of a stylesheet."""
    index = (styles or "").find("@media")
    if index < 0:
        return ""
    start = styles.index("{", index)
    depth = 0
    for position in range(start, len(styles)):
        if styles[position] == "{":
            depth += 1
        elif styles[position] == "}":
            depth -= 1
            if depth == 0:
                return styles[start + 1 : position]
    return ""


def css_rules(styles):
    """The rules of a stylesheet: a selector and its declarations."""
    return [
        (match.group(1).strip(), match.group(2))
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", styles or "")
    ]


def clipped_selectors(styles):
    """The selectors of the narrow screen that cut the text of their element."""
    return [
        selector
        for selector, declarations in css_rules(media_body(styles))
        if "text-overflow: ellipsis" in declarations
    ]


def provider_name_target(panel):
    """The target that carries the name a provider is read by."""
    for target in panel.get("targets") or []:
        if '"providerName"' in (target.get("expr") or ""):
            return target
    raise AssertionError(f"no target of {panel.get('title')!r} names the provider")


def fixture_capacity_rows():
    """The rows of the capacity panel, read from the committed fixture.

    The panel reads the account window gauges in one query, so a row is one
    series of one gauge: the labels of the window, the field the series
    fills and its value.
    """
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)$", line)
        if not match:
            continue
        metric, inner, value = match.groups()
        field = CAPACITY_METRICS.get(metric)
        if field is None:
            continue
        labels = {}
        for part in (inner or "").split(","):
            if not part:
                continue
            key, _, label = part.partition("=")
            labels[key.strip()] = label.strip().strip('"')
        rows.append({**labels, "field": field, "value": float(value)})
    return rows


# The metrics of the static route table and of the free selection under it,
# and the field of a row each one fills. The panel reads them in one query,
# and the field says which one a row holds.
SELECTION_METRICS = {
    "ghostship_ai_static_route_info": "info",
    "ghostship_ai_static_route_remaining_ratio": "left",
    "ghostship_ai_static_route_paced_availability": "pace",
    "ghostship_ai_static_route_reset_timestamp_seconds": "reset",
    # The free selection of every free provider, published by the collector.
    "ghostship_ai_free_provider_selection_info": "free_info",
    "ghostship_ai_free_provider_selection_remaining_ratio": "free_left",
    "ghostship_ai_free_provider_selection_paced_availability": "free_pace",
    "ghostship_ai_free_provider_selection_reset_timestamp_seconds": "free_reset",
    "ghostship_ai_provider_free_models": "free_models",
}

# The metrics of the free selection alone. The page reads them; it never
# computes a free row from the candidates or from the account windows.
FREE_SELECTION_METRICS = (
    "ghostship_ai_free_provider_selection_info",
    "ghostship_ai_free_provider_selection_remaining_ratio",
    "ghostship_ai_free_provider_selection_paced_availability",
    "ghostship_ai_free_provider_selection_reset_timestamp_seconds",
    "ghostship_ai_provider_free_models",
)

# The live static route table the owner approved: row, role, provider, model,
# display name and the work the route is used for.
STATIC_ROUTES = (
    ("1", "Bulk 1", "ollama", "minimax-m3.1-flash", "MiniMax-M3.1-Flash",
     "Narrow implementation (1st), Research (2nd)"),
    ("2", "Bulk 2", "ollama", "deepseek-v4.1-flash:1017",
     "DeepSeek V4.1 Flash 1017",
     "Narrow implementation (2nd), Research (1st)"),
    ("3", "Large", "codex", "gpt-6.1-sol", "GPT-6.1-Sol",
     "Large implementation (1st)"),
    ("4", "Deploys", "opencode-go", "beam-free", "Beam Free",
     "Deploys (1st), Research (3rd)"),
    ("5", "Deploys", "ollama", "beam", "Beam 1.0 501B A23B", "Deploys (2nd)"),
)

# The live free selection under the static rows, at the moment of the
# fixture: the provider, the name the cards read it by, the model the
# provider selected for the free tier, the name of that model, and the Left
# cell. The rows follow the capacity cards: the approved accounts first, then
# the accounts the list does not name, by name.
FREE_ROWS = (
    ("opencode-go", "OpenCode Go", "beam-free", "Beam Free", "100%"),
    ("openrouter", "OpenRouter", "gpt-oss-120b", "GPT OSS 120B",
     "99% \u00b7 \u25cf on pace"),
    ("cloudflare-workers-ai", "Cloudflare", "llama-3.3-70b-instruct",
     "Llama 3.3 70B Instruct", "learning window"),
    ("cohere", "Cohere", "", "", "no eligible free model"),
    ("google", "Google", "gemma-3-27b", "Gemma 3 27B",
     "97% \u00b7 \u25b2 33 ahead"),
    ("groq", "Groq", "qwen3.8-27b", "Qwen3.8 27B", "learning window"),
    ("inception", "Inception", "mercury-2", "Mercury 2", "learning window"),
    ("kilo", "Kilo", "nemotron-3.5-super-vl", "Nemotron 3.5 Super VL",
     "learning window"),
    ("kilo-keyed", "Kilo (keyed)", "qwen3.8-27b", "Qwen3.8 27B",
     "learning window"),
    ("mistral", "Mistral", "", "", "no eligible free model"),
    ("nvidia", "NVIDIA", "glm-5.3-flash", "GLM-5.3 Flash", "learning window"),
    ("ovh", "OVH", "mistral-small-3.2", "Mistral Small 3.2",
     "learning window"),
    ("opencode", "OpenCode Zen", "", "", "no eligible free model"),
    ("orcarouter", "Orcarouter", "", "", "no eligible free model"),
    ("poolside", "Poolside", "", "", "no eligible free model"),
    ("requesty", "Requesty", "", "", "no eligible free model"),
)

# The free models of every provider that holds a free route, by state, as the
# collector counts them at the moment of the fixture. A provider that holds no
# free route publishes no count, so its card carries no free line.
FREE_MODEL_COUNTS = {
    "google": (8, 0),
    "kilo": (8, 4),
    "nvidia": (15, 1),
    "opencode-go": (2, 3),
    "openrouter": (10, 10),
    "requesty": (0, 7),
}


def labels_of(inner):
    """The labels of a series of the fixture, commas inside a value included."""
    labels = {}
    for match in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"', inner or ""):
        labels[match.group(1)] = match.group(2)
    return labels


def fixture_selection_rows():
    """The rows of the static route table, read from the committed fixture.

    The panel reads the info series and the three capacity series in one
    query, so a row is one series: the labels of the route (on the info
    series only) and the field the series fills. The routing gauge is a row
    of its own, read by the chip.
    """
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)$", line)
        if not match:
            continue
        metric, inner, value = match.groups()
        field = SELECTION_METRICS.get(metric)
        if field is None:
            if metric != "ghostship_ai_routing_enabled":
                continue
            field = "routing"
        rows.append({**labels_of(inner), "field": field, "value": float(value)})
    return rows


def fixture_free_rows():
    """The rows of the free selection, read from the committed fixture.

    The panel reads the info series, the three capacity series and the count
    of free models in the same query as the static routes, so a row is one
    series and its field says which one it fills. The count carries the state
    of the free route in the `state` label.
    """
    return [
        row
        for row in fixture_selection_rows()
        if str(row.get("field") or "").startswith("free_")
    ]


def run_panel_helper(panel, expression, env=None):
    """The answer of a helper of the panel, run the way Business Text runs it.

    Business Text runs the helpers code as new Function("context", code) and
    hands it context.handlebars; the test runs it the same way.
    """
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("node is needed to run the helper")
    script = (
        "const helpers = {};\n"
        "const context = { handlebars: { registerHelper: (name, fn) => { helpers[name] = fn; } } };\n"
        "new Function('context', " + json.dumps(panel["options"]["helpers"]) + ")(context);\n"
        + expression
        + "\n"
    )
    result = subprocess.run(
        [node, "-e", script],
        capture_output=True,
        text=True,
        env=env or dict(os.environ),
        check=True,
    )
    return json.loads(result.stdout)


class Template:
    """The elements of a template, with their classes and their children."""

    def __init__(self, content):
        from html.parser import HTMLParser

        outer = self
        self.nodes = []
        self.roots = []

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []

            def handle_starttag(self, tag, attrs):
                node = {
                    "tag": tag,
                    "classes": (dict(attrs).get("class") or "").split(),
                    "children": [],
                    "parent": self.stack[-1] if self.stack else None,
                }
                outer.nodes.append(node)
                if self.stack:
                    self.stack[-1]["children"].append(node)
                else:
                    outer.roots.append(node)
                if tag not in ("br", "img", "hr", "input"):
                    self.stack.append(node)

            def handle_endtag(self, tag):
                if self.stack:
                    self.stack.pop()

            def handle_data(self, data):
                if self.stack and data.strip():
                    self.stack[-1]["children"].append({"text": data.strip()})

        parser = Parser()
        parser.feed(content or "")
        parser.close()

    def matches(self, node, selector):
        """True when a node matches a selector of class names."""
        parts = [part for part in selector.split() if part]
        if not parts:
            return False
        names = [name for name in parts[-1].split(".") if name]
        if not all(name in node.get("classes", []) for name in names):
            return False
        if len(parts) == 1:
            return True
        # A descendant selector: the last part is the node, the others are
        # its ancestors.
        parent = node.get("parent")
        while parent is not None:
            if self.matches(parent, " ".join(parts[:-1])):
                return True
            parent = parent.get("parent")
        return False

    def tags(self):
        """The tag elements of the template."""
        return [node for node in self.nodes if "tag" in node["classes"]]

    def inside(self, node, selectors):
        """True when a node or one of its ancestors matches a selector."""
        current = node
        while current is not None:
            for selector in selectors:
                if self.matches(current, selector):
                    return True
            current = current.get("parent")
        return False


class ProvidersPageTests(unittest.TestCase):
    """The shape of the page."""

    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    def test_the_as_of_time_is_written_in_utc(self):
        """The header says UTC, so the time it shows is UTC, whatever the viewer's zone.

        Grafana's `__to:date:` format renders in the viewer's own time zone,
        so the header showed a local time under a UTC label. The time is now
        formatted by a helper that reads only the UTC fields of the end time.
        """
        header = next(
            panel for panel, _collapsed in panels(self.page) if panel.get("id") == 200
        )
        content = header["options"]["content"]
        self.assertNotIn("__to:date", content)
        self.assertIn('{{utcStamp (variable "__to")}} UTC', content)
        helpers = header["options"]["helpers"]
        node = shutil.which("node")
        if node is None:
            self.fail("node is needed to run the helper")
        # Business Text runs the helpers code as new Function("context", code)
        # and hands it context.handlebars; the test runs it the same way.
        script = (
            "const helpers = {};\n"
            "const context = { handlebars: { registerHelper: (name, fn) => { helpers[name] = fn; } } };\n"
            "new Function('context', " + json.dumps(helpers) + ")(context);\n"
            "console.log(helpers.utcStamp(String(Date.UTC(2026, 9, 22, 19, 5, 0))));\n"
            "console.log(JSON.stringify(helpers.utcStamp('not a time')));"
        )
        # A viewer far from UTC: the helper must not use the local zone.
        env = dict(os.environ, TZ="Etc/GMT+10")
        result = subprocess.run(
            [node, "-e", script], capture_output=True, text=True, env=env, check=True
        )
        self.assertEqual(result.stdout.split("\n")[:2], ["22 Oct 19:05", '""'])

    def test_every_reset_time_is_written_in_utc(self):
        """A reset time reads in UTC, like the header, whatever the viewer's zone."""
        node = shutil.which("node")
        if node is None:
            self.fail("node is needed to run the helper")
        for title in ("Bulk", "Free", "Frontier", "3D"):
            panel = section(self.page, title)
            content = panel["options"]["content"]
            self.assertNotIn('{{date resetsAt', content, title)
            self.assertIn("{{utcClock resetsAt}} UTC", content, title)
            script = (
                "const helpers = {};\n"
                "const context = { handlebars: { registerHelper: (name, fn) => { helpers[name] = fn; } } };\n"
                "new Function('context', " + json.dumps(panel["options"]["helpers"]) + ")(context);\n"
                "const at = Date.UTC(2026, 9, 22, 13, 0, 0);\n"
                "console.log(helpers.utcClock(at / 1000));\n"
                "console.log(helpers.utcClock(at));"
            )
            env = dict(os.environ, TZ="Etc/GMT+10")
            result = subprocess.run(
                [node, "-e", script], capture_output=True, text=True, env=env, check=True
            )
            self.assertEqual(result.stdout.split("\n")[:2], ["13:00", "13:00"], title)

    def test_the_frontier_lists_only_its_two_roles(self):
        """Capacity is read per model, so Frontier keeps only the rows that hold a role."""
        panel = section(self.page, "Frontier")
        filters = [s for s in panel["transformations"] if s["id"] == "filterByValue"]
        self.assertEqual(len(filters), 1)
        self.assertEqual(
            [rule["fieldName"] for rule in filters[0]["options"]["filters"]], ["rank"]
        )

    def test_the_3d_table_has_room_for_its_live_rows_on_a_phone(self):
        """Live, 3D has four winners; at 390 px the fourth row was cut at the panel edge.

        Measured on the live page: a height of 8 grid rows gave a 296 px panel
        for a 231 px table plus its title and subtitle. Eleven rows hold it.
        """
        self.assertGreaterEqual(section(self.page, "3D")["gridPos"]["h"], 11)

    def test_no_two_top_level_panels_overlap(self):
        """Resizing a panel moves the panels below it; none of them overlap."""
        boxes = [
            (p["gridPos"]["x"], p["gridPos"]["y"], p["gridPos"]["w"], p["gridPos"]["h"], p.get("title", ""))
            for p in self.page["panels"]
        ]
        for i, (x1, y1, w1, h1, t1) in enumerate(boxes):
            for x2, y2, w2, h2, t2 in boxes[i + 1:]:
                overlap = x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1
                self.assertFalse(overlap, f"{t1!r} overlaps {t2!r}")

    def test_every_business_text_panel_has_the_options_the_plugin_maps(self):
        """Live, Model selection read "An unexpected error happened".

        Business Text 6.3.0 calls `.map` on externalStyles, editors and
        contentPartials, so an empty string in place of a list throws
        "e.externalStyles.map is not a function" and the whole panel fails.
        Its queries are read as one table, as every other section's are.
        """
        for panel, _collapsed in panels(self.page):
            if panel.get("type") != "marcusolsson-dynamictext-panel":
                continue
            name = panel.get("title") or panel.get("id")
            for option in ("externalStyles", "editors", "contentPartials"):
                self.assertIsInstance(panel["options"].get(option), list, f"{name}: {option}")
            for target in panel.get("targets") or []:
                if target.get("expr"):
                    self.assertEqual(target.get("format"), "table", f"{name}: {target.get('refId')}")

    def test_the_sections_are_in_the_owner_s_order(self):
        """The owner reads the page from the top: Bulk, Free, Frontier, 3D, Providers."""
        titles = [
            panel.get("title", "").split(" · ")[0]
            for panel, collapsed in panels(self.page)
            if not collapsed and panel.get("type") == "marcusolsson-dynamictext-panel"
        ]
        self.assertEqual(titles[1:], list(SECTIONS))
        self.assertEqual(titles[0], "", "the header carries no title of its own")

    def test_every_section_reads_the_collector_s_own_winner_position(self):
        """A tier that ordered itself would show a different route than the collector picks."""
        for title, tier in TIERS.items():
            panel = section(self.page, title)
            joined = expressions(panel)
            self.assertIn(
                f'ghostship_ai_model_winner_position{{tier="{tier}"', joined, title
            )
            for other in set(TIERS.values()) - {tier}:
                self.assertNotIn(
                    f'ghostship_ai_model_winner_position{{tier="{other}"', joined, title
                )
            # The order is the collector's position, not a ranking made here.
            order = find_target(panel, "ghostship_ai_model_winner_position")
            self.assertNotIn("ghostship_ai_model_paced_availability", order["expr"], title)

    def test_the_order_of_a_tier_is_the_collector_s_position(self):
        """The rows are sorted by the collector's own key, and the panel does not re-rank."""
        for title in TIERS:
            if title == "Frontier":
                # Frontier's rows are the owner's two roles, not a ranking:
                # see test_the_frontier_reads_chief_then_backup.
                continue
            panel = section(self.page, title)
            sorts = [t for t in panel.get("transformations") or [] if t["id"] == "sortBy"]
            self.assertEqual(len(sorts), 1, title)
            self.assertEqual(sorts[0]["options"]["sort"][0]["field"], "order", title)
            self.assertTrue(sorts[0]["options"]["sort"][0]["desc"], title)

    def test_the_frontier_reads_chief_then_backup(self):
        """The Frontier rows are the chief and the backup, in that order, as the concept shows."""
        panel = section(self.page, "Frontier")
        sorts = [t for t in panel.get("transformations") or [] if t["id"] == "sortBy"]
        self.assertEqual(sorts[0]["options"]["sort"], [{"field": "role", "desc": True}])
        # Descending order of the role names puts Chief before Backup.
        self.assertEqual(sorted(["Backup", "Chief"], reverse=True), ["Chief", "Backup"])

    def test_capacity_is_read_per_model_not_per_tier(self):
        """A model's capacity series carries one tier label, so no tier table filters on it.

        Live, every 3D row read "Limits unknown": the collector publishes a
        model's capacity once, labelled with its first tier (GPT-6.1-Sol's is
        frontier), and the 3D table asked for tier="3d".
        """
        for title in TIERS:
            panel = section(self.page, title)
            for target in panel["targets"]:
                self.assertNotRegex(
                    target["expr"],
                    r'ghostship_ai_model_capacity_remaining\{tier=',
                    f"{title} {target['refId']}",
                )

    def test_the_3d_reserve_tag_is_shown_only_where_it_applies(self):
        """The reserve changes the order of Bulk and Free; Frontier and 3D carry no tag."""
        for title in ("Frontier", "3D"):
            content = section(self.page, title)["options"]["content"]
            self.assertNotIn("3D reserve", content, title)
        for title in ("Bulk", "Free"):
            content = section(self.page, title)["options"]["content"]
            self.assertIn("3D reserve", content, title)

    def test_the_3d_table_lists_its_winners_and_the_routes_that_are_out(self):
        panel = section(self.page, "3D")
        filters = [step for step in panel["transformations"] if step["id"] == "filterByValue"]
        self.assertEqual(len(filters), 1)
        self.assertEqual(
            sorted(rule["fieldName"] for rule in filters[0]["options"]["filters"]),
            ["out", "rank"],
        )

    def test_no_bargauge_or_stat_panel_sits_outside_a_collapsed_row(self):
        """The owner asked for tables, not gauges: the gauges stay in the evidence."""
        for panel, collapsed in panels(self.page):
            if panel.get("type") in ("bargauge", "stat"):
                self.assertTrue(collapsed, panel.get("title"))

    def test_no_template_prints_unescaped_html(self):
        """A model name is label text: it is escaped, never printed raw."""
        for panel, _ in panels(self.page):
            content = json.dumps(panel.get("options") or {})
            self.assertNotIn("{{{", content, panel.get("title"))
            self.assertNotIn("innerHTML", content, panel.get("title"))
            self.assertNotIn("<script", content, panel.get("title"))

    def test_the_expected_left_is_the_share_left_minus_the_paced_availability(self):
        """The line in the bar is the share the window expects to be left now."""
        for title in TIERS:
            panel = section(self.page, title)
            expected = target_by_field(panel, "expected")
            self.assertIn("ghostship_ai_model_capacity_remaining", expected["expr"], title)
            self.assertIn("ghostship_ai_model_paced_availability", expected["expr"], title)
            self.assertIn("clamp_min", expected["expr"], title)
            self.assertIn("clamp_max", expected["expr"], title)

    def test_the_capacity_bar_reads_the_share_left_now(self):
        """The fill of a bar is the share left now, and the percentage sits beside it."""
        for title in TIERS:
            panel = section(self.page, title)
            content = panel["options"]["content"]
            self.assertIn("ghostship_ai_model_capacity_remaining", expressions(panel), title)
            self.assertIn('style="width:{{left}}"', content, title)
            self.assertIn('class="pct"', content, title)
            self.assertIn('style="left:{{expected}}"', content, title)

    def test_the_pace_reads_the_paced_availability(self):
        """The pace of a route is the collector's number, read as points."""
        for title in TIERS:
            panel = section(self.page, title)
            joined = expressions(panel)
            self.assertIn("ghostship_ai_model_paced_availability", joined, title)
            self.assertIn("round(100 *", joined, title)
        # The free tier has no pace column: it answers with one response, and
        # the owner reads its quality band instead.
        for title in ("Bulk", "Frontier", "3D"):
            content = section(self.page, title)["options"]["content"]
            self.assertIn("ahead", content, title)
            self.assertIn("behind", content, title)
            self.assertIn("on pace", content, title)
            self.assertIn("no window", content, title)

    def test_an_unknown_allowance_is_never_a_zero_and_never_a_red_bar(self):
        """A route whose limits are unknown says so; it never looks spent."""
        for title in TIERS:
            content = section(self.page, title)["options"]["content"]
            self.assertIn("Limits unknown", content, title)
            self.assertIn("{{#if hasCap}}", content, title)
            self.assertIn("{{#if hasPace}}", content, title)

    def test_a_promotion_route_reads_as_unlimited(self):
        """A route the provider publishes as unlimited for a limited time says so."""
        for title in TIERS:
            panel = section(self.page, title)
            self.assertIn("Unlimited · promotion", panel["options"]["content"], title)
            self.assertIn('ghostship_ai_entitlement_info{basis="promotion"', expressions(panel), title)

    def test_the_display_name_falls_back_to_the_raw_model_id(self):
        """The name a person would say when the collector publishes one, the id otherwise."""
        for title in TIERS:
            content = section(self.page, title)["options"]["content"]
            self.assertIn("{{#if name}}{{name}}{{else}}{{model}}{{/if}}", content, title)

    def test_the_routing_chip_reads_the_collector_s_gauge(self):
        """The chip is the collector's routing state, not a fixed text.

        The selection table carries the static table either way: its own
        chip says so and reads the same gauge in its own query, and the
        table below it does not change with the routing.
        """
        header = section(self.page, "")
        joined = expressions(header)
        self.assertIn("ghostship_ai_routing_enabled", joined)
        content = header["options"]["content"]
        self.assertIn("Routing ON", content)
        self.assertIn("Routing OFF · awaiting your approval", content)
        # The chip is one branch of one condition: the gauge decides it.
        self.assertIn(
            "{{#if (eq routing 1)}}Routing ON{{else}}Routing OFF · awaiting your approval{{/if}}",
            content,
        )

    def test_no_hard_coded_routing_text_sits_outside_the_chip(self):
        """Only the chip of the header says the routing is off."""
        for panel, _ in panels(self.page):
            if panel.get("id") in (200, 206):
                continue
            self.assertNotIn("Routing OFF", json.dumps(panel), panel.get("title"))
            self.assertNotIn("Routing ON", json.dumps(panel), panel.get("title"))

    def test_a_route_with_no_limit_seen_says_so_and_draws_no_bar(self):
        """An inferred capacity with no failure seen is not a measured allowance."""
        for title in TIERS:
            content = section(self.page, title)["options"]["content"]
            self.assertIn("No limit seen", content, title)
            # The text comes before the bar: a route with no limit seen never
            # draws one.
            self.assertLess(
                content.index("No limit seen"), content.index('class="barrow"'), title
            )
            self.assertIn("ghostship_ai_model_capacity_basis", expressions(section(self.page, title)), title)

    def test_an_inferred_route_carries_its_tag(self):
        """The tag says that the capacity was inferred, and which window."""
        for title in TIERS:
            content = section(self.page, title)["options"]["content"]
            self.assertIn("inferred · {{window}}", content, title)
            self.assertIn('class="tag"', content, title)

    def test_the_reasons_of_the_collector_are_read_as_words(self):
        """No cell of the page carries a raw code of the collector."""
        codes = set()
        for line in FIXTURE.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            labels = line.split("}", 1)[0]
            for part in labels.split("{", 1)[-1].split(","):
                if part.startswith("reason=") or part.startswith("window="):
                    codes.add(part.split("=", 1)[1].strip('"'))
        self.assertTrue(codes, "the fixture carries the codes of the collector")
        page = DASHBOARD.read_text(encoding="utf-8")
        for code in codes:
            if "_" not in code:
                continue
            # The code is either mapped by a query of the page, or read with
            # its underscores turned into spaces by the template.
            self.assertTrue(
                f'^{code}$' in page or f'"{code}"' in page or "join (split" in page,
                f"{code} would reach the page as it is",
            )
        for title in list(TIERS) + ["Model selection"]:
            content = section(self.page, title)["options"]["content"]
            self.assertNotIn("no_window", content, title)

    def test_the_evidence_rows_stay_below_the_page_and_collapsed(self):
        """The detail is still there, and it is still out of the way."""
        rows = [panel for panel, collapsed in panels(self.page) if panel.get("type") == "row"]
        why = [row for row in rows if row.get("title", "").startswith("Why this order")]
        self.assertGreaterEqual(len(why), 5)
        for row in why:
            self.assertTrue(row.get("collapsed"), row.get("title"))
        header = section(self.page, "")
        last_section = max(
            panel["gridPos"]["y"]
            for panel, collapsed in panels(self.page)
            if not collapsed and panel.get("type") == "marcusolsson-dynamictext-panel"
        )
        for row in why:
            self.assertGreater(row["gridPos"]["y"], last_section)

    def test_a_hidden_column_hides_its_cells_too(self):
        """A column that goes away on a narrow screen takes its cells with it.

        The header of the basis column went away while the cells stayed, so
        the columns of the table no longer lined up.
        """
        for title in list(TIERS) + ["Model selection"]:
            head, row = table_columns(section(self.page, title)["options"]["content"])
            self.assertEqual(len(head), len(row), title)
            for index, (header, cell) in enumerate(zip(head, row)):
                self.assertEqual(
                    hide_marker(header),
                    hide_marker(cell),
                    f"{title} column {index}: {header!r} and {cell!r}",
                )

    def test_the_order_of_a_tier_reads_the_spent_routes(self):
        """The order of a table depends on the route that cannot be used.

        Without it the spent route keeps the place the collector gave it, and
        it stands above the routes that can run.
        """
        for title in TIERS:
            panel = section(self.page, title)
            order = target_by_field(panel, "order")["expr"]
            spent = target_by_field(panel, "out")["expr"]
            self.assertIn(inner(spent), order, title)

    def test_the_basis_cell_reads_the_basis_of_the_collector(self):
        """The basis column names where the limit of a route comes from."""
        panel = section(self.page, "Free")
        content = panel["options"]["content"]
        self.assertIn("{{#if basis}}{{basis}}{{else}}unknown{{/if}}", content)
        # The limit of a provider is not the basis of a route.
        self.assertNotIn("limitBasis", content)
        self.assertNotIn("ghostship_ai_provider_limit", expressions(panel))

    def test_a_tag_is_never_a_clipped_box(self):
        """The narrow screen hides the tag of a route: it is never a cut grey box.

        The name of the model and its tag shared one line that the narrow
        screen cut, so the tag became an empty grey box.
        """
        for title in list(TIERS) + ["Model selection"]:
            panel = section(self.page, title)
            styles = panel["options"].get("styles") or ""
            rules = css_rules(media_body(styles))
            declarations = " ".join(
                body
                for name, body in rules
                if ".tag" in [selector.strip() for selector in name.split(",")]
            )
            self.assertIn("display: none", declarations, title)
        # The tiers carry the tags of the collector.
        self.assertTrue(
            Template(section(self.page, "Bulk")["options"]["content"]).tags()
        )

    def test_the_narrow_screen_holds_one_line(self):
        """A row of a narrow screen is one line: the name, the provider and the capacity.

        A row that wraps is a row the panel cuts, and the rows a rule
        sinks to the bottom are the last ones of the table.
        """
        for title in TIERS:
            panel = section(self.page, title)
            styles = panel["options"].get("styles") or ""
            rules = css_rules(media_body(styles))
            for selector in (".name", ".prov", ".unk"):
                declarations = " ".join(
                    body
                    for name, body in rules
                    if selector in [part.strip() for part in name.split(",")]
                )
                self.assertIn("white-space: nowrap", declarations, f"{title} {selector}")
                self.assertIn("overflow: hidden", declarations, f"{title} {selector}")
                self.assertIn("text-overflow: ellipsis", declarations, f"{title} {selector}")

    def test_the_capacity_text_carries_its_whole_text(self):
        """The capacity text of a narrow screen is cut with an ellipsis: the title holds it all."""
        for title in TIERS:
            content = section(self.page, title)["options"]["content"]
            self.assertIn('class="unk" title="', content, title)

    def test_every_provider_is_read_by_its_name(self):
        """A provider is read by the name the mockup gives it."""
        for title in TIERS:
            expression = provider_name_target(section(self.page, title))["expr"]
            for identifier, name in PROVIDER_NAMES.items():
                self.assertIn(f'"^{identifier}$"', expression, f"{title} {identifier}")
                self.assertIn(f'"{name}"', expression, f"{title} {name}")

    def test_the_on_pace_pace_carries_its_number_on_a_narrow_screen(self):
        """Every pace of a narrow screen carries a number: the on-pace one reads '● 0'."""
        for title in ("Bulk", "Frontier", "3D"):
            panel = section(self.page, title)
            content = panel["options"]["content"]
            styles = panel["options"].get("styles") or ""
            self.assertIn('<span class="na">●', content, title)
            self.assertIn('<span class="narrow"> 0</span>', content, title)
            # The narrow screen shows the number, the wide one the words.
            self.assertIn(".narrow { display: inline; }", media_body(styles), title)
            self.assertIn(".narrow { display: none; }", styles, title)


class ProviderCapacityTests(unittest.TestCase):
    """The capacity cards the page opens with.

    One card per account, one row per window of the account, and the
    accounts that publish no window of their own as a chip. The numbers are
    the collector's account window gauges, so the worked cases are the rows
    of the committed fixture and not a copy of them.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        cls.rows = fixture_capacity_rows()

    def setUp(self):
        self.panel = section(self.page, "Provider capacity")

    def cards(self, rows=None, now=CAPACITY_NOW, env=None):
        """The cards of the page, as the helper of the panel builds them."""
        expression = (
            "const rows = "
            + json.dumps(self.rows if rows is None else rows)
            + ";\n"
            + "const now = "
            + json.dumps(now)
            + ";\n"
            + "console.log(JSON.stringify(helpers.capacityCards(rows, now)));"
        )
        return run_panel_helper(self.panel, expression, env=env)

    def learning(self, rows=None, env=None):
        """The line of the accounts that are learning, as the helper builds it."""
        expression = (
            "const rows = "
            + json.dumps(self.rows if rows is None else rows)
            + ";\n"
            + "console.log(JSON.stringify(helpers.learningLine(rows)));"
        )
        return run_panel_helper(self.panel, expression, env=env)

    def card(self, cards, account):
        for card in cards:
            if card["account"] == account:
                return card
        raise AssertionError(f"no card for {account!r}")

    def window(self, card, label):
        for window in card["windows"]:
            if window["label"] == label:
                return window
        raise AssertionError(f"no window {label!r} in the card of {card['account']!r}")

    def test_the_page_opens_with_the_capacity_cards(self):
        """The cards are the first thing the page shows, under the header."""
        header = next(
            panel for panel, _collapsed in panels(self.page) if panel.get("id") == 200
        )
        self.assertEqual(self.panel["title"], "Provider capacity")
        self.assertEqual(
            header["gridPos"]["y"] + header["gridPos"]["h"],
            self.panel["gridPos"]["y"],
        )

    def test_the_cards_read_the_collector_s_account_windows(self):
        """Every number of a card is a gauge the collector publishes."""
        expression = expressions(self.panel)
        for metric in CAPACITY_METRICS:
            self.assertIn(metric, expression, metric)
        # The freshness guard the other panels of the page read.
        self.assertIn("ghostship_ai_collection_duration_seconds", expression)

    def test_the_cards_are_in_the_approved_order(self):
        """The order of the cards is the one the owner approved."""
        cards = self.cards()
        self.assertEqual(
            [card["account"] for card in cards],
            [
                "claude",
                "codex",
                "ollama",
                "opencode-go",
                "antigravity",
                "grok",
                "openrouter",
                # An account the approved list does not name follows it, by
                # its name.
                "cursor",
                "example-free",
                "google",
                "opencode",
                "requesty",
            ],
        )

    def test_the_fixture_holds_the_set_the_height_is_sized_for(self):
        """Twelve cards, twenty-two windows and seventeen learning accounts.

        The panel is sized for the live set with the headroom of the next
        collection, so the count of the fixture is the count the height
        answers to.
        """
        cards = self.cards()
        learning = self.rows
        self.assertEqual(len(cards), 12)
        self.assertEqual(sum(len(card["windows"]) for card in cards), 22)
        self.assertEqual(
            len([row for row in learning if row.get("field") == "learning"]), 17
        )
        self.assertEqual(len(self.learning()), 1)

    def test_the_labels_carry_their_scope(self):
        """A window that covers one model family names it, as #267 publishes it."""
        cards = self.cards()
        labels = [
            window["label"]
            for card in cards
            for window in card["windows"]
        ]
        for label in (
            "Session · Claude & GPT",
            "Weekly · Claude & GPT",
            "Quota · Gemini",
            "Quota · Claude & GPT",
            "Weekly · Fable",
        ):
            self.assertIn(label, labels)
        self.assertEqual(
            [
                window["label"]
                for window in self.card(cards, "antigravity")["windows"]
            ],
            [
                "Session · Gemini",
                "Weekly · Gemini",
                "Quota · Gemini",
                "Quota · Claude & GPT",
            ],
        )

    def test_the_identity_of_a_card_is_the_approved_one(self):
        """A card carries the name, the icon and the note the owner approved."""
        cards = self.cards()
        approved = {
            "claude": ("Claude", "✳", "#d97757", "subscription"),
            "codex": ("Codex", "⊛", "#e8e8e8", "subscription"),
            "ollama": ("Ollama", "◉", "#f2f2f2", "subscription · shared with 3D"),
            "opencode-go": ("OpenCode Go", "{}", "#2b2f3a", "subscription"),
            "antigravity": ("Antigravity", "A", "linear-gradient", "subscription"),
            "grok": ("Grok", "⊘", "#000", "subscription · 3D reserve"),
            "openrouter": ("OpenRouter", "⇄", "#6466f1", "free daily"),
        }
        for account, (name, icon, background, meta) in approved.items():
            card = self.card(cards, account)
            self.assertEqual(card["name"], name, account)
            self.assertEqual(card["icon"], icon, account)
            self.assertIn(background, card["background"], account)
            self.assertEqual(card["meta"], meta, account)

    def test_the_worked_rows_read_the_collector_s_numbers(self):
        """The three worked rows read exactly what the owner saw."""
        cards = self.cards()
        self.assertEqual(
            self.window(self.card(cards, "claude"), "Session · Claude & GPT")["sub"],
            "▲ 24 ahead · resets in 2h 9m (22 Oct 23:09)",
        )
        self.assertEqual(
            self.window(self.card(cards, "ollama"), "Weekly")["sub"], "● on pace"
        )
        self.assertEqual(
            self.window(self.card(cards, "opencode-go"), "Monthly")["sub"],
            "✕ spent · resets in 8.1d (30 Oct 22:34)",
        )

    def test_a_spent_window_is_red_and_draws_an_empty_bar(self):
        """A window that is spent reads spent, and its bar is empty."""
        cards = self.cards()
        window = self.window(self.card(cards, "grok"), "Weekly")
        self.assertEqual(window["paceClass"], "spent")
        self.assertEqual(window["fillClass"], "spent")
        self.assertEqual(window["width"], "0")
        self.assertEqual(window["pct"], "0%")
        self.assertTrue(window["sub"].startswith("✕ spent · resets in "))

    def test_a_window_with_no_expected_series_has_no_tick_and_no_pace_word(self):
        """A window with no even-spend line draws no line and says no pace."""
        cards = self.cards()
        window = self.window(
            self.card(cards, "antigravity"), "Quota · Claude & GPT"
        )
        self.assertFalse(window["hasTick"])
        self.assertEqual(window["tick"], "")
        self.assertEqual(window["paceClass"], "")
        self.assertEqual(window["sub"], "")
        self.assertEqual(window["pct"], "100%")

    def test_a_window_with_a_reset_and_no_expected_line_prints_the_reset_alone(self):
        """The reset of a window is printed even when the window has no pace."""
        rows = [
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "left",
                "value": 0.5,
            },
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "resetAt",
                "value": CAPACITY_NOW / 1000 + 3600,
            },
        ]
        window = self.window(self.card(self.cards(rows=rows), "example-free"), "Weekly")
        self.assertEqual(window["sub"], "resets in 1h 0m (22 Oct 22:01)")
        self.assertFalse(window["hasTick"])

    def test_a_learning_account_is_one_line_and_not_a_card(self):
        """An account with no window of its own says so under the cards.

        The chips of seventeen learning accounts were a grid of boxes that
        took six rows of a phone; one wrapped line says the same thing.
        """
        line = self.learning()
        self.assertEqual(len(line), 1)
        self.assertEqual(
            line[0]["text"],
            "Kilo, NVIDIA, Groq, Cloudflare, Cohere, DeepSeek, Inception, "
            "Kilo (keyed), Mistral, Moonshot, OVH, Orcarouter, Pi, Poolside, "
            "Upstage, Vercel, Zai",
        )
        self.assertIn(
            "Learning: {{this.text}}", self.panel["options"]["content"]
        )
        self.assertNotIn("ichip", self.panel["options"]["content"])

    def test_an_account_without_a_window_is_never_on_the_line(self):
        """The line holds the accounts that publish no window, and only them."""
        names = self.learning()[0]["text"].split(", ")
        self.assertEqual(len(names), 17)
        # Google and Requesty hold a window of their own, so they are cards.
        for name in ("Google", "Requesty", "OpenCode Zen", "Claude"):
            self.assertNotIn(name, names)
        for name in ("Kilo", "NVIDIA", "Groq"):
            self.assertIn(name, names)

    def test_an_account_with_no_window_holds_no_card(self):
        """A card is an account that has a window to show."""
        learning = {
            row["account"] for row in self.rows if row.get("field") == "learning"
        }
        self.assertEqual(len(learning), 17)
        accounts = [card["account"] for card in self.cards()]
        for account in learning:
            self.assertNotIn(account, accounts)

    def test_an_inferred_window_carries_its_tag(self):
        """A window the provider did not report says that it was inferred."""
        cards = self.cards()
        window = self.window(self.card(cards, "example-free"), "Inferred · 5h")
        self.assertTrue(window["inferred"])
        self.assertFalse(
            self.window(self.card(cards, "claude"), "Session · Claude & GPT")["inferred"]
        )

    def test_a_window_with_no_remaining_is_never_a_zero_bar(self):
        """A window the collector could not read is not a window that is spent."""
        rows = [
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "order",
                "value": 3,
            }
        ]
        window = self.window(self.card(self.cards(rows=rows), "example-free"), "Weekly")
        self.assertFalse(window["hasLeft"])
        self.assertEqual(window["width"], "")
        self.assertEqual(window["pct"], "")

    def test_the_reset_time_is_written_in_utc(self):
        """A reset time reads in UTC, whatever the viewer's zone."""
        env = dict(os.environ, TZ="Etc/GMT+10")
        cards = self.cards(env=env)
        self.assertEqual(
            self.window(self.card(cards, "claude"), "Session · Claude & GPT")["sub"],
            "▲ 24 ahead · resets in 2h 9m (22 Oct 23:09)",
        )
        self.assertEqual(
            self.window(self.card(cards, "opencode-go"), "Monthly")["sub"],
            "✕ spent · resets in 8.1d (30 Oct 22:34)",
        )

    def test_the_share_left_reads_one_decimal(self):
        """The share left is written with one decimal, so it can be compared.

        The owner compares it with the provider's own site, which writes
        95.9% and 39.5%. A whole number hides the second digit, and the
        trailing zero of 100% is noise.
        """
        rows = []
        for index, (label, left) in enumerate(
            (("A", 0.9585), ("B", 0.3948), ("C", 1.0), ("D", 0.0))
        ):
            rows.append(
                {
                    "account": "example-free",
                    "kind": "weekly",
                    "quota_id": label,
                    "label": label,
                    "evidence": "provider_reported",
                    "field": "left",
                    "value": left,
                }
            )
            rows.append(
                {
                    "account": "example-free",
                    "kind": "weekly",
                    "quota_id": label,
                    "label": label,
                    "evidence": "provider_reported",
                    "field": "order",
                    "value": index,
                }
            )
        windows = self.card(self.cards(rows=rows), "example-free")["windows"]
        self.assertEqual(
            [window["pct"] for window in windows],
            ["95.9%", "39.5%", "100%", "0%"],
        )
        self.assertEqual(windows[0]["width"], "95.9")
        cards = self.cards()
        ollama = self.card(cards, "ollama")
        self.assertEqual(self.window(ollama, "Session")["pct"], "95.9%")
        self.assertEqual(self.window(ollama, "Weekly")["pct"], "39.5%")
        self.assertEqual(self.window(ollama, "Session")["width"], "95.9")

    def test_a_reset_in_the_past_reads_resets_now(self):
        """A window that is due says so: it never counts down to '0m'."""
        cards = self.cards()
        window = self.window(self.card(cards, "opencode"), "Inferred · 1h")
        self.assertEqual(window["sub"], "● on pace · resets now")
        self.assertEqual(window["brief"], "● on pace · resets now")
        for text in (window["sub"], window["brief"]):
            self.assertNotIn("0m", text)
            self.assertNotIn("resets in", text)
        # One minute before its reset, and one minute after: the words differ.
        rows = [
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "left",
                "value": 0.5,
            },
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "resetAt",
                "value": CAPACITY_NOW / 1000 - 60,
            },
        ]
        past = self.window(self.card(self.cards(rows=rows), "example-free"), "Weekly")
        self.assertEqual(past["sub"], "resets now")

    def test_a_rolling_window_says_rolling_and_nothing_else(self):
        """A rolling window has no reset, no tick and no pace.

        The collector marks an inferred window shorter than five minutes
        with ghostship_ai_account_window_rolling, and the window rolls: there
        is nothing to reset and nothing to pace against.
        """
        cards = self.cards()
        window = self.window(self.card(cards, "opencode"), "Inferred · 1m")
        self.assertTrue(window["rolling"])
        self.assertEqual(window["sub"], "rolling 1m")
        self.assertEqual(window["brief"], "rolling 1m")
        self.assertFalse(window["hasTick"])
        self.assertEqual(window["tick"], "")
        self.assertEqual(window["paceClass"], "")
        self.assertEqual(window["pct"], "100%")
        for text in (window["sub"], window["brief"]):
            self.assertNotIn("resets", text)
            self.assertNotIn("pace", text)
        # The mark of the fixture is the collector's, one on the window.
        marks = [
            row
            for row in self.rows
            if row.get("field") == "rolling" and row.get("value") == 1
        ]
        self.assertEqual([row["label"] for row in marks], ["Inferred · 1m"])

    def test_the_card_says_how_old_its_reading_is(self):
        """A card dates its reading from the oldest window it holds.

        The card is compared with the provider's own site, so the age of the
        reading is part of it: Ollama was checked two minutes ago.
        """
        cards = self.cards()
        self.assertEqual(self.card(cards, "ollama")["read"], "read 2m ago")
        ollama = self.card(cards, "ollama")
        checked = [
            row["value"]
            for row in self.rows
            if row.get("account") == "ollama" and row.get("field") == "checked"
        ]
        self.assertEqual(len(checked), 2)
        self.assertEqual(max(checked), CAPACITY_NOW / 1000 - 120)
        # The age is the oldest window, not the freshest one.
        rows = [
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "checked",
                "value": CAPACITY_NOW / 1000 - 60,
            },
            {
                "account": "example-free",
                "kind": "monthly",
                "quota_id": "monthly",
                "label": "Monthly",
                "evidence": "provider_reported",
                "field": "checked",
                "value": CAPACITY_NOW / 1000 - 600,
            },
        ]
        card = self.card(self.cards(rows=rows), "example-free")
        self.assertEqual(card["read"], "read 10m ago")

    def test_a_window_without_a_check_time_dates_nothing(self):
        """A reading without a check time prints no age."""
        rows = [
            {
                "account": "example-free",
                "kind": "weekly",
                "quota_id": "weekly",
                "label": "Weekly",
                "evidence": "provider_reported",
                "field": "left",
                "value": 0.5,
            }
        ]
        card = self.card(self.cards(rows=rows), "example-free")
        self.assertEqual(card["read"], "")

    def test_the_narrow_line_drops_the_clock_and_never_wraps(self):
        """A phone row is one line of the window and one of its pace.

        The clock of the reset is dropped on the narrow screen, and neither
        line wraps: a long label such as 'Quota · Claude & GPT' stays on its
        row. The wide screen keeps the clock.
        """
        window = self.window(
            self.card(self.cards(), "claude"), "Session · Claude & GPT"
        )
        self.assertEqual(window["brief"], "▲ 24 ahead · resets in 2h 9m")
        self.assertIn("(22 Oct 23:09)", window["sub"])
        for label in (
            self.window(self.card(self.cards(), "antigravity"), "Quota · Claude & GPT"),
            self.window(self.card(self.cards(), "claude"), "Session · Claude & GPT"),
        ):
            self.assertNotIn("(", label["brief"])
        styles = self.panel["options"]["styles"]
        rules = dict(css_rules(styles))
        narrow = media_body(styles)
        for selector in (".capacity .wl", ".capacity .sub"):
            self.assertIn("white-space: nowrap", rules[selector], selector)
        # The label column is as wide as the label, so no label is cut.
        self.assertIn("max-content", rules[".capacity .card"])
        # The narrow screen shows the brief line and hides the clocked one.
        self.assertIn(".capacity .sub .wide { display: none; }", narrow)
        self.assertIn(".capacity .sub .brief { display: inline; }", narrow)
        self.assertIn(".capacity .sub .brief { display: none; }", styles)

    def test_the_panel_has_one_heading(self):
        """The panel title is the heading: the content does not repeat it."""
        content = self.panel["options"]["content"]
        self.assertNotIn("<h2>", content)
        self.assertNotIn("Provider capacity", content)
        # Its chip and the as-of time stay on that line.
        self.assertIn('% left · tick = where you should be now', content)
        self.assertIn('{{utcStamp (variable "__to")}} UTC', content)
        self.assertNotIn("<h2>", self.panel["options"]["defaultContent"])

    def test_the_account_is_read_by_its_name(self):
        """The Zen account of OpenCode is read as OpenCode Zen."""
        card = self.card(self.cards(), "opencode")
        self.assertEqual(card["name"], "OpenCode Zen")
        self.assertEqual(card["icon"], "O")

    def test_no_window_of_the_page_is_a_fixed_value(self):
        """The page reads every number of a window; it never holds one."""
        page = json.dumps(self.panel)
        for value in (
            "0.67",
            "0.429",
            "0.9585",
            "0.3948",
            "0.4463",
            "0.9994",
            "0.881",
            "0.966",
            "1792710599",
            "1793399640",
            "1792702757",
        ):
            self.assertNotIn(value, page, value)

    def test_the_panel_is_tall_enough_for_its_cards(self):
        """The panel holds every card, every row and the learning line.

        Measured in Playwright with the panel's own helpers, styles and the
        production font (Inter), at the widths the owner uses: the content is
        1798 px tall at 390 px and 538 px at 1600 px with the free line of
        every card that holds free models. The taller reading is rounded up
        to whole 37 px grid rows.
        """
        rows = math.ceil(CAPACITY_PHONE_HEIGHT / CAPACITY_ROW_HEIGHT)
        self.assertEqual(rows, 49)
        self.assertEqual(self.panel["gridPos"]["h"], rows)
        self.assertGreaterEqual(
            self.panel["gridPos"]["h"] * CAPACITY_ROW_HEIGHT,
            CAPACITY_PHONE_HEIGHT,
        )
        self.assertGreaterEqual(
            self.panel["gridPos"]["h"] * CAPACITY_ROW_HEIGHT,
            CAPACITY_DESKTOP_HEIGHT,
        )

    # --- The free models of a card -------------------------------------------

    def test_a_card_reads_the_free_models_apart_from_its_allowance(self):
        """The free models of a card are the collector's own count."""
        self.assertIn(
            "ghostship_ai_provider_free_models", expressions(self.panel)
        )
        content = self.panel["options"]["content"]
        self.assertIn('class="fr {{this.free.cls}}"', content)
        self.assertIn("{{this.free.text}}", content)
        styles = self.panel["options"].get("styles") or ""
        # The line is green when a free model is available, grey otherwise.
        self.assertIn(".capacity .fr {", styles)
        self.assertIn(".capacity .fr.ok { color: #8fc98f; }", styles)

    def test_a_card_with_available_free_models_says_available(self):
        """OpenCode Go is the case: its monthly is spent, its free route works."""
        monthly = self.window(self.card(self.cards(), "opencode-go"), "Monthly")
        self.assertEqual(monthly["pct"], "0%")
        self.assertEqual(monthly["fillClass"], "spent")
        card = self.card(self.cards(), "opencode-go")
        self.assertEqual(
            card["free"], {"text": "Free models \u00b7 available \u00b7 2 models", "cls": "ok"}
        )
        # A provider whose free routes are all available counts the available
        # ones, never the paid allowance.
        google = self.card(self.cards(), "google")
        self.assertEqual(
            google["free"],
            {"text": "Free models \u00b7 available \u00b7 8 models", "cls": "ok"},
        )

    def test_a_card_with_no_available_free_model_says_none_available(self):
        """Requesty holds seven free routes and none of them is available."""
        card = self.card(self.cards(), "requesty")
        self.assertEqual(
            card["free"],
            {"text": "Free models \u00b7 none available \u00b7 7 models", "cls": ""},
        )
        # OpenRouter counts its available routes, not all of them.
        openrouter = self.card(self.cards(), "openrouter")
        self.assertEqual(
            openrouter["free"],
            {"text": "Free models \u00b7 available \u00b7 10 models", "cls": "ok"},
        )

    def test_an_account_with_no_free_model_has_no_free_line(self):
        """A provider that publishes no free route has no free line at all."""
        cards = self.cards()
        for account in ("ollama", "claude", "codex", "opencode"):
            self.assertIsNone(self.card(cards, account)["free"], account)

    def test_the_free_line_is_sized_with_its_card(self):
        """The free line is a line of its own in the card, in the card's font."""
        styles = self.panel["options"].get("styles") or ""
        rule = next(
            declarations
            for selector, declarations in css_rules(styles)
            if selector == ".capacity .fr"
        )
        self.assertIn("grid-column: 1 / -1", rule)
        self.assertIn("font-size: 10.5px", rule)
        self.assertIn("white-space: nowrap", rule)


class ModelSelectionTests(unittest.TestCase):
    """The static route table the page shows under the capacity cards.

    One row per route of the owner's static table, in the collector's row
    order: the role, the model and its tag, the provider, the work the route
    is used for, and the share of its window that is left with the pace
    beside it. The numbers are the collector's static route series, so the
    worked cases are the rows of the committed fixture and not a copy of
    them.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        cls.rows = fixture_selection_rows()

    def setUp(self):
        self.panel = section(self.page, "Model selection")

    def selection(self, rows=None, now=CAPACITY_NOW):
        """The rows of the table, as the helper of the panel builds them."""
        expression = (
            "const rows = "
            + json.dumps(self.rows if rows is None else rows)
            + ";\n"
            + "const now = "
            + json.dumps(now)
            + ";\n"
            + "console.log(JSON.stringify(helpers.selectionRows(rows, now)));"
        )
        return run_panel_helper(self.panel, expression)

    def chip(self, rows):
        """The text and the routing state of the chip, from the rows."""
        expression = (
            "const rows = "
            + json.dumps(rows)
            + ";\n"
            + "console.log(JSON.stringify([helpers.selectionChip(rows), helpers.selectionRouting(rows)]));"
        )
        return run_panel_helper(self.panel, expression)

    def free(self, rows=None, now=CAPACITY_NOW):
        """The divider and the free rows, as the helper of the panel builds them.

        The helper reads the collector's free selection only: no candidate and
        no account window is turned into a free row here.
        """
        self.assertIn(
            "selectionFreeRows",
            self.panel["options"]["helpers"],
            "the panel has no helper for the free rows",
        )
        expression = (
            "const rows = "
            + json.dumps(self.rows if rows is None else rows)
            + ";\n"
            + "const now = "
            + json.dumps(now)
            + ";\n"
            + "console.log(JSON.stringify(helpers.selectionFreeRows(rows, now)));"
        )
        return run_panel_helper(self.panel, expression)

    def free_row(self, rows=None, now=CAPACITY_NOW, provider="opencode-go"):
        """The free row of one provider, and the divider it follows."""
        built = self.free(rows, now)
        self.assertEqual(built[0].get("group"), "Free", "the free group has no divider")
        for row in built[1:]:
            if row["provider"] == provider:
                return row
        raise AssertionError(f"no free row for {provider!r}")

    def test_the_page_puts_the_selection_under_the_capacity_cards(self):
        """The owner reads the cards first, then the static table, then the rankings."""
        capacity = section(self.page, "Provider capacity")
        bulk = section(self.page, "Bulk")
        self.assertEqual(self.panel["title"], "Model selection")
        self.assertEqual(
            capacity["gridPos"]["y"] + capacity["gridPos"]["h"],
            self.panel["gridPos"]["y"],
        )
        self.assertEqual(
            self.panel["gridPos"]["y"] + self.panel["gridPos"]["h"],
            bulk["gridPos"]["y"],
        )
        # Nothing else stands above the table but the header and the cards.
        above = [
            panel.get("title", "")
            for panel, collapsed in panels(self.page)
            if not collapsed
            and panel.get("type") == "marcusolsson-dynamictext-panel"
            and panel["gridPos"]["y"] < self.panel["gridPos"]["y"]
        ]
        self.assertEqual(above, ["", "Provider capacity"])

    def test_the_old_providers_table_is_gone(self):
        """The cards replace the provider table: it is not on the page any more."""
        self.assertFalse(
            [panel for panel, _collapsed in panels(self.page) if panel.get("id") == 205]
        )
        self.assertNotIn(
            "Providers", [panel.get("title", "") for panel, _collapsed in panels(self.page)]
        )

    def test_the_table_reads_the_collector_s_static_routes(self):
        """Every number of the table is a static route series of the collector."""
        expression = expressions(self.panel)
        for metric in SELECTION_METRICS:
            self.assertIn(metric, expression, metric)
        self.assertIn("ghostship_ai_routing_enabled", expression)
        # A row counts only if it is from the newest scrape.
        self.assertIn("ghostship_ai_static_route_policy_ok", expression)
        self.assertIn(") - 15", expression)

    def test_every_selection_series_reads_only_the_newest_scrape(self):
        """No series of the table is read from an older scrape than the newest.

        The guard was 90 s wide while a scrape is 30 s, so after a policy
        edit the rows of the policy before it stayed on the table for about
        two minutes. The policy gauge is published on every collection, so
        its newest timestamp is the newest scrape.
        """
        expression = expressions(self.panel)
        guard = "scalar(max(timestamp(ghostship_ai_static_route_policy_ok))) - 15"
        self.assertNotIn("ghostship_ai_collection_duration_seconds", expression)
        self.assertEqual(expression.count(guard), 10)
        for metric in SELECTION_METRICS:
            self.assertIn(f"timestamp({metric}", expression, metric)
        self.assertIn("timestamp(ghostship_ai_routing_enabled)", expression)

    def test_the_columns_are_role_model_provider_used_for_and_left(self):
        """The table reads in the owner's columns, and Left comes last."""
        content = self.panel["options"]["content"]
        head = re.search(r"<thead>(.*?)</thead>", content, re.S).group(1)
        self.assertEqual(
            re.findall(r"<th[^>]*>([^<]*)</th>", head),
            ["Role", "Model", "Provider", "Used for", "Left"],
        )
        head_cells, row_cells = table_columns(content)
        for index, (header, cell) in enumerate(zip(head_cells, row_cells)):
            self.assertEqual(
                hide_marker(header), hide_marker(cell), f"column {index}"
            )

    def test_the_table_draws_no_bar(self):
        """The selection is a static table: it has no bar and no track."""
        content = self.panel["options"]["content"]
        styles = self.panel["options"].get("styles") or ""
        for className in ('class="bar"', 'class="track"', 'class="fill"', 'class="barrow"'):
            self.assertNotIn(className, content)
        for rule in (".bar", ".track", ".fill", ".barrow", ".mark", ".tick"):
            self.assertNotIn(rule + " ", styles, rule)
            self.assertNotIn(rule + "{", styles, rule)

    def test_the_left_cell_carries_the_share_and_the_pace(self):
        """The cell reads the share left, a dot, and the pace beside it.

        The share keeps the colour of the row; the pace alone is grey on
        pace, green ahead, amber behind and red when spent, as on the cards.
        """
        content = self.panel["options"]["content"]
        self.assertIn(
            '<span class="pct">{{leftPct}}</span>', content
        )
        self.assertIn(
            '<span class="pace {{leftClass}}">{{leftPace}}</span>', content
        )
        styles = self.panel["options"].get("styles") or ""
        self.assertIn(".left .pace { color: #8b8f99;", styles)
        self.assertIn(".left .pace.spent { color: #d9534f; }", styles)
        self.assertIn(".left .pace.ahead { color: #8fc98f; }", styles)
        self.assertIn(".left .pace.behind { color: #e0a03a; }", styles)

    def test_the_chip_reads_the_routing_gauge(self):
        """The chip is the collector's routing state, and the table is static."""
        off = [row for row in self.rows if row["field"] != "routing"]
        off.append({"field": "routing", "value": 0.0})
        self.assertEqual(
            self.chip(off), ["Static table \u00b7 routing OFF", 0]
        )
        on = [row for row in self.rows if row["field"] != "routing"]
        on.append({"field": "routing", "value": 1.0})
        self.assertEqual(
            self.chip(on),
            ["Routing ON \u00b7 static table shown for reference", 1],
        )

    def test_the_fixture_holds_the_live_route_table(self):
        """The five live rows: role, provider, model, name and work, in order."""
        rows = self.selection()
        self.assertEqual(
            [(row["row"], row["role"]) for row in rows],
            [(row[0], row[1]) for row in STATIC_ROUTES],
        )
        self.assertEqual(
            [row["model"] for row in rows], [row[3] for row in STATIC_ROUTES]
        )
        self.assertEqual(
            [row["displayName"] for row in rows], [row[4] for row in STATIC_ROUTES]
        )
        self.assertEqual(
            [row["usedFor"] for row in rows], [row[5] for row in STATIC_ROUTES]
        )
        self.assertEqual(
            [row["providerName"] for row in rows],
            ["Ollama", "Ollama", "Codex", "OpenCode Go", "Ollama"],
        )
        # The bulk roles carry the blue bulk tag, the other rows none.
        self.assertEqual([row["tag"] for row in rows], ["bulk", "bulk", "", "", ""])

    def test_the_worked_left_cells(self):
        """41% on pace, 99% on pace, and 100% with no pace series at all."""
        rows = {row["model"]: row for row in self.selection()}
        self.assertEqual(rows["minimax-m3.1-flash"]["left"], "41% \u00b7 \u25cf on pace")
        self.assertEqual(rows["gpt-6.1-sol"]["left"], "99% \u00b7 \u25cf on pace")
        self.assertEqual(rows["beam-free"]["left"], "100%")
        self.assertEqual(rows["beam-free"]["leftClass"], "")

    def test_a_spent_route_reads_spent_and_its_reset(self):
        """A spent route reads zero, spent, and how long until it resets."""
        now = CAPACITY_NOW / 1000
        rows = [row for row in self.rows if row["field"] != "routing"]
        rows += [
            {
                "row": "9",
                "field": "info",
                "role": "Bulk 3",
                "provider": "grok",
                "model": "grok-like",
                "display_name": "Grok",
                "used_for": "Research (4th)",
                "value": 1.0,
            },
            {"row": "9", "field": "left", "value": 0.0},
            {"row": "9", "field": "reset", "value": now + 4.4 * 86400},
        ]
        spent = next(row for row in self.selection(rows) if row["row"] == "9")
        self.assertEqual(spent["left"], "0% \u00b7 \u2715 spent \u00b7 resets in 4.4d")
        self.assertEqual(spent["leftClass"], "spent")

    def test_a_route_ahead_or_behind_reads_its_points(self):
        """More than ten points off the pace reads ahead or behind."""
        now = CAPACITY_NOW / 1000

        def route(pace):
            rows = [
                {
                    "row": "7",
                    "field": "info",
                    "role": "Free 1",
                    "provider": "ollama",
                    "model": "worked",
                    "display_name": "Worked",
                    "used_for": "Research",
                    "value": 1.0,
                },
                {"row": "7", "field": "left", "value": 0.5},
                {"row": "7", "field": "reset", "value": now + 3600},
            ]
            if pace is not None:
                rows.append({"row": "7", "field": "pace", "value": pace})
            return next(row for row in self.selection(rows) if row["row"] == "7")

        self.assertEqual(route(0.15)["left"], "50% \u00b7 \u25b2 15 ahead")
        self.assertEqual(route(0.15)["leftClass"], "ahead")
        self.assertEqual(route(-0.2)["left"], "50% \u00b7 \u25bc 20 behind")
        self.assertEqual(route(-0.2)["leftClass"], "behind")
        # Ten points is still on the pace.
        self.assertEqual(route(0.1)["left"], "50% \u00b7 \u25cf on pace")
        self.assertEqual(route(-0.1)["left"], "50% \u00b7 \u25cf on pace")

    def test_a_route_with_no_remaining_reading_says_so(self):
        """A route the snapshot does not carry has no share, and never a zero."""
        rows = [
            {
                "row": "8",
                "field": "info",
                "role": "Large",
                "provider": "codex",
                "model": "unread",
                "display_name": "Unread",
                "used_for": "Large implementation (2nd)",
                "value": 1.0,
            }
        ]
        route = next(row for row in self.selection(rows) if row["row"] == "8")
        self.assertEqual(route["left"], "no reading")
        self.assertEqual(route["leftClass"], "")

    def test_the_provider_name_and_icon_come_from_the_capacity_cards(self):
        """The table reads a provider as the cards do: same name, icon and colour."""
        capacity = section(self.page, "Provider capacity")
        cards = run_panel_helper(
            capacity,
            "const rows = "
            + json.dumps(["ollama", "codex", "opencode-go"])
            + ".map((account) => ({ account: account, kind: 'session', quota_id: 'q', label: 'Session', evidence: 'provider_reported', field: 'left', value: 1 }));\n"
            + "console.log(JSON.stringify(helpers.capacityCards(rows, 0)));",
        )
        by_provider = {card["account"]: card for card in cards}
        selected = {row["provider"]: row for row in self.selection()}
        for provider in ("ollama", "codex", "opencode-go"):
            card = by_provider[provider]
            row = selected[provider]
            for key in ("name", "icon", "background", "foreground"):
                self.assertEqual(
                    row["providerName" if key == "name" else key],
                    card[key],
                    f"{provider} {key}",
                )

    def test_a_phone_row_names_its_provider_in_the_model_cell(self):
        """Under 520 px the hidden Provider column's name moves under the model.

        A free row with no model held only the letter icon on a phone, and the
        owner could not tell which provider it was. The name is hidden at the
        wide width, where the Provider column carries it.
        """
        content = self.panel["options"]["content"]
        self.assertEqual(
            content.count('<span class="mp">{{providerName}}</span>'),
            2,
            "the static row and the free row carry the provider name in the model cell",
        )
        self.assertIn('<td class="hide-sm">{{providerName}}</td>', content)
        styles = self.panel["options"].get("styles") or ""
        base = styles[: styles.find("@media")]
        self.assertIn("display: none", dict(css_rules(base))[".routes .mp"])
        self.assertIn(
            "display: block", dict(css_rules(media_body(styles)))[".routes .mp"]
        )
        row = self.free_row(provider="cohere")
        self.assertEqual(row["providerName"], "Cohere")
        self.assertEqual(row["model"], "")
        self.assertEqual(row["displayName"], "")
        self.assertEqual(row["left"], "no eligible free model")

    def test_a_model_name_is_one_line_and_carries_its_id(self):
        """A model name ends in an ellipsis on one line, the full id in its title.

        On a phone a long raw id wrapped through the Left cell. The name is
        one line in its own cell now, and the title holds the whole id.
        """
        content = self.panel["options"]["content"]
        self.assertEqual(content.count('class="mn" title="{{model}}"'), 2)
        styles = self.panel["options"].get("styles") or ""
        base = dict(css_rules(styles[: styles.find("@media")]))
        self.assertIn("white-space: nowrap", base[".routes .mn"])
        self.assertIn("text-overflow: ellipsis", base[".routes .mn"])
        self.assertIn("min-width: 0", base[".routes .mid"])
        self.assertIn("min-width: 0", base[".routes .mrow"])
        media = dict(css_rules(media_body(styles)))
        for declaration in (
            "white-space: nowrap",
            "overflow: hidden",
            "text-overflow: ellipsis",
        ):
            self.assertIn(declaration, media[".routes .mn"])
        # A row that carries only the raw id reads it as its name.
        rows = [
            {
                "provider": "kilo",
                "field": "free_info",
                "model": "nvidia/nemotron-3.5-super-vl:free",
                "display_name": "",
                "basis": "learning",
                "value": 1,
            }
        ]
        row = self.free_row(rows, provider="kilo")
        self.assertEqual(row["displayName"], "nvidia/nemotron-3.5-super-vl:free")

    def test_the_panel_is_tall_enough_for_its_rows(self):
        """The panel holds every row of the live table at either width.

        Measured in Playwright with the panel's own styles, the production
        font (Inter) and the headroom of twenty free providers: the content is
        883 px tall at 390 px and 861 px at 1600 px, and a grid row of the
        dashboard is 37 px. The live set holds sixteen free providers, so the
        height keeps room for four more.
        """
        self.assertEqual(self.panel["gridPos"]["h"] * 37, 888)
        self.assertGreaterEqual(
            self.panel["gridPos"]["h"] * 37, SELECTION_PHONE_HEIGHT
        )
        self.assertGreaterEqual(
            self.panel["gridPos"]["h"] * 37, SELECTION_DESKTOP_HEIGHT
        )

    def test_the_fixture_routes_have_no_numbers_the_store_disagrees_with(self):
        """The fixture is the live table, and the page reads it, not a copy."""
        rows = {
            (row["row"], row["field"]): row["value"]
            for row in self.rows
            if "row" in row
        }
        self.assertAlmostEqual(rows[("1", "left")], 0.4129)
        self.assertAlmostEqual(rows[("1", "pace")], -0.033)
        self.assertAlmostEqual(rows[("3", "left")], 0.99)
        self.assertAlmostEqual(rows[("3", "pace")], 0.012)
        self.assertAlmostEqual(rows[("4", "left")], 1.0)
        self.assertNotIn(("4", "pace"), rows)

    # --- The free group under the static rows --------------------------------

    def test_the_free_rows_read_the_collector_s_free_selection(self):
        """Every number of a free row is a series the collector publishes.

        The page never builds a free row from the candidates or from the
        account windows: a row that is not published is not on the page.
        """
        expression = expressions(self.panel)
        for metric in FREE_SELECTION_METRICS:
            self.assertIn(metric, expression, metric)
        self.assertIn("ghostship_ai_static_route_policy_ok", expression)
        for metric in (
            "ghostship_ai_model_winner_position",
            "ghostship_ai_account_window_",
            "ghostship_ai_model_capacity_",
            "ghostship_ai_entitlement_",
        ):
            self.assertNotIn(metric, expression, metric)

    def test_the_free_rows_follow_the_static_rows_behind_a_divider(self):
        """The static rows come first, then one divider, then the free rows."""
        content = self.panel["options"]["content"]
        static = content.find("(selectionRows")
        free = content.find("(selectionFreeRows")
        self.assertGreaterEqual(static, 0, "the page has no static rows")
        self.assertGreater(free, static, "the free rows are not under the static rows")
        divider = re.search(r"<tr class=\"group\">.*?</tr>", content, re.S)
        self.assertIsNotNone(divider, "the free group has no divider row")
        row = divider.group(0)
        # The divider spans the table without a colspan: a spanned cell would
        # take the room the hidden columns leave on a narrow screen.
        self.assertNotIn("colspan", row)
        self.assertEqual(len(re.findall(r"<td[\s>]", row)), 5)
        self.assertIn("Free", row)
        self.assertIn('class="role"', row)
        built = self.free()
        self.assertEqual(built[0], {"group": "Free"})
        self.assertEqual(
            [row["role"] for row in built[1:]], ["Free"] * len(FREE_ROWS)
        )
        self.assertEqual([row["tag"] for row in built[1:]], [""] * len(FREE_ROWS))

    def test_the_free_rows_are_in_the_order_of_the_capacity_cards(self):
        """A free provider follows the cards: the approved accounts, then by name."""
        built = self.free()
        self.assertEqual(
            [row["provider"] for row in built[1:]],
            [row[0] for row in FREE_ROWS],
        )
        self.assertEqual(
            [(row["providerName"], row["displayName"]) for row in built[1:]],
            [(row[1], row[3]) for row in FREE_ROWS],
        )

    def test_an_opencode_go_free_route_reads_its_published_share(self):
        """Beam Free is a route the provider publishes: 100%, with no pace."""
        row = self.free_row(provider="opencode-go")
        self.assertEqual(row["model"], "beam-free")
        self.assertEqual(row["displayName"], "Beam Free")
        self.assertEqual(row["basis"], "published")
        self.assertEqual(row["leftPct"], "100%")
        self.assertEqual(row["leftPace"], "")
        self.assertEqual(row["leftClass"], "")
        self.assertEqual(row["left"], "100%")

    def test_a_google_inferred_selection_reads_its_points_ahead(self):
        """97% with a Paced Availability of 33 points reads ahead of the pace."""
        row = self.free_row(provider="google")
        self.assertEqual(row["basis"], "inferred")
        self.assertEqual(row["leftPct"], "97%")
        self.assertEqual(row["leftPace"], "\u25b2 33 ahead")
        self.assertEqual(row["leftClass"], "ahead")
        self.assertEqual(row["left"], "97% \u00b7 \u25b2 33 ahead")

    def test_a_learning_selection_reads_the_learning_window(self):
        """An account that never saw a limit failure is learning its window."""
        row = self.free_row(provider="nvidia")
        self.assertEqual(row["basis"], "learning")
        self.assertEqual(row["leftPct"], "")
        self.assertEqual(row["leftPace"], "learning window")
        self.assertEqual(row["leftClass"], "")
        self.assertEqual(row["left"], "learning window")

    def test_a_selection_with_no_eligible_model_says_so(self):
        """A free provider with no winner reads one sentence, not a zero."""
        row = self.free_row(provider="requesty")
        self.assertEqual(row["basis"], "none")
        self.assertEqual(row["model"], "")
        self.assertEqual(row["leftPct"], "")
        self.assertEqual(row["leftPace"], "no eligible free model")
        self.assertEqual(row["left"], "no eligible free model")

    def test_a_spent_selection_reads_spent_and_its_reset(self):
        """A selection at zero reads spent, and its reset when it has one."""
        now = CAPACITY_NOW / 1000

        def spent(reset):
            rows = [
                {
                    "provider": "google",
                    "field": "free_info",
                    "model": "gemma-3-27b",
                    "display_name": "Gemma 3 27B",
                    "basis": "inferred",
                    "value": 1.0,
                },
                {"provider": "google", "field": "free_left", "value": 0.0},
            ]
            if reset is not None:
                rows.append({"provider": "google", "field": "free_reset", "value": reset})
            return self.free_row(rows, provider="google")

        with_reset = spent(now + 4.4 * 86400)
        self.assertEqual(
            with_reset["left"], "0% \u00b7 \u2715 spent \u00b7 resets in 4.4d"
        )
        self.assertEqual(with_reset["leftPct"], "0%")
        self.assertEqual(with_reset["leftPace"], "\u2715 spent \u00b7 resets in 4.4d")
        self.assertEqual(with_reset["leftClass"], "spent")
        without_reset = spent(None)
        self.assertEqual(without_reset["left"], "0% \u00b7 \u2715 spent")
        self.assertEqual(without_reset["leftPace"], "\u2715 spent")

    def test_the_free_rows_name_their_provider_as_the_cards_do(self):
        """The provider of a free row is the name and the icon of its card."""
        capacity = section(self.page, "Provider capacity")
        providers = [row[0] for row in FREE_ROWS]
        cards = run_panel_helper(
            capacity,
            "const rows = "
            + json.dumps(providers)
            + ".map((account) => ({ account: account, kind: 'session', quota_id: 'q', "
            "label: 'Session', evidence: 'provider_reported', field: 'left', value: 1 }));\n"
            + "console.log(JSON.stringify(helpers.capacityCards(rows, 0)));",
        )
        by_provider = {card["account"]: card for card in cards}
        selected = {row["provider"]: row for row in self.free()[1:]}
        for provider, name, _model, _display, _left in FREE_ROWS:
            card = by_provider[provider]
            row = selected[provider]
            self.assertEqual(row["providerName"], name, provider)
            self.assertEqual(row["providerName"], card["name"], provider)
            for key in ("icon", "background", "foreground"):
                self.assertEqual(row[key], card[key], f"{provider} {key}")
        # The account of the OpenCode API is read as its card reads it.
        self.assertEqual(selected["opencode"]["providerName"], "OpenCode Zen")

    def test_the_free_group_draws_no_bar(self):
        """A free row is a row of the table: it has no bar and no track."""
        content = self.panel["options"]["content"]
        start = content.find("(selectionFreeRows")
        self.assertGreaterEqual(start, 0, "the page has no free rows")
        free = content[start:]
        self.assertIn("<td", free)
        for className in ('class="bar"', 'class="fill"', 'class="track"', 'class="mark"'):
            self.assertNotIn(className, free, className)

    def test_the_fixture_holds_the_live_free_selection(self):
        """The fixture is the free selection of the live set, and the page reads it."""
        rows = fixture_free_rows()
        info = {
            row["provider"]: row for row in rows if row["field"] == "free_info"
        }
        self.assertEqual(len(info), len(FREE_ROWS))
        self.assertEqual(sorted(info), sorted(row[0] for row in FREE_ROWS))
        expected = {
            "opencode-go": ("beam-free", "published"),
            "openrouter": ("gpt-oss-120b", "reported"),
            "cloudflare-workers-ai": ("llama-3.3-70b-instruct", "learning"),
            "cohere": ("", "none"),
            "google": ("gemma-3-27b", "inferred"),
            "groq": ("qwen3.8-27b", "learning"),
            "inception": ("mercury-2", "learning"),
            "kilo": ("nemotron-3.5-super-vl", "learning"),
            "kilo-keyed": ("qwen3.8-27b", "learning"),
            "mistral": ("", "none"),
            "nvidia": ("glm-5.3-flash", "learning"),
            "ovh": ("mistral-small-3.2", "learning"),
            "opencode": ("", "none"),
            "orcarouter": ("", "none"),
            "poolside": ("", "none"),
            "requesty": ("", "none"),
        }
        self.assertEqual(
            {provider: (row["model"], row["basis"]) for provider, row in info.items()},
            expected,
        )
        self.assertEqual(len(info), 16)  # the live set of the free providers

        left = {
            row["provider"]: row["value"]
            for row in rows
            if row["field"] == "free_left"
        }
        self.assertAlmostEqual(left["google"], 0.9712)
        self.assertAlmostEqual(left["openrouter"], 0.992)
        self.assertAlmostEqual(left["opencode-go"], 1.0)
        pace = {
            row["provider"]: row["value"]
            for row in rows
            if row["field"] == "free_pace"
        }
        self.assertAlmostEqual(pace["google"], 0.33)
        self.assertAlmostEqual(pace["openrouter"], 0.041)
        counts = {
            (row["provider"], row["state"]): int(row["value"])
            for row in rows
            if row["field"] == "free_models"
        }
        for provider, (available, unavailable) in FREE_MODEL_COUNTS.items():
            self.assertEqual(counts[(provider, "available")], available, provider)
            self.assertEqual(counts[(provider, "unavailable")], unavailable, provider)
        # A provider with no free route publishes no count at all.
        self.assertEqual(
            {provider for provider, _state in counts}, set(FREE_MODEL_COUNTS)
        )


@unittest.skipUnless(
    os.environ.get("GHOSTSHIP_TEST_VMETRICS") or shutil.which("victoria-metrics"),
    "Set GHOSTSHIP_TEST_VMETRICS or put victoria-metrics on the path",
)
class ModelSelectionStoreTests(unittest.TestCase):
    """The static route query, executed against the store the page reads."""

    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        cls.store = VictoriaMetricsFixture()
        if not cls.store.start():
            raise unittest.SkipTest("VictoriaMetrics did not start")
        cls.store.import_fixture(FIXTURE)

    @classmethod
    def tearDownClass(cls):
        cls.store.stop()

    def test_the_query_returns_the_live_route_table(self):
        """The panel's own query is the five live routes and the routing gauge."""
        panel = section(self.page, "Model selection")
        target = find_target(panel, "ghostship_ai_static_route_info")
        rows = self.store.wait_for(target["expr"].replace("$provider", ".*"))
        by_field = {}
        for row in rows:
            by_field.setdefault(row["metric"].get("field"), []).append(row)
        self.assertEqual(
            set(by_field),
            {
                "info", "left", "pace", "reset", "routing",
                "free_info", "free_left", "free_pace", "free_reset", "free_models",
            },
        )
        info = {row["metric"]["row"]: row["metric"] for row in by_field["info"]}
        self.assertEqual(sorted(info), ["1", "2", "3", "4", "5"])
        self.assertEqual(
            (info["1"]["role"], info["1"]["provider"], info["1"]["model"]),
            ("Bulk 1", "ollama", "minimax-m3.1-flash"),
        )
        self.assertEqual(info["1"]["display_name"], "MiniMax-M3.1-Flash")
        self.assertEqual(
            info["1"]["used_for"], "Narrow implementation (1st), Research (2nd)"
        )
        self.assertEqual(info["4"]["display_name"], "Beam Free")
        self.assertEqual([float(row["value"][1]) for row in by_field["routing"]], [0.0])
        # Beam Free publishes no pace series at all.
        self.assertEqual(
            [row["metric"]["row"] for row in by_field["pace"]], ["1", "2", "3", "5"]
        )
        expression = (
            "const rows = "
            + json.dumps(
                [{**row["metric"], "value": float(row["value"][1])} for row in rows]
            )
            + ";\n"
            + "const now = "
            + json.dumps(CAPACITY_NOW)
            + ";\n"
            + "console.log(JSON.stringify(helpers.selectionRows(rows, now)));"
        )
        left = {
            row["model"]: row["left"] for row in run_panel_helper(panel, expression)
        }
        self.assertEqual(left["minimax-m3.1-flash"], "41% \u00b7 \u25cf on pace")
        self.assertEqual(left["gpt-6.1-sol"], "99% \u00b7 \u25cf on pace")
        self.assertEqual(left["beam-free"], "100%")

    def test_the_query_returns_the_free_selection_of_every_free_provider(self):
        """The same query returns the free selection the collector publishes."""
        panel = section(self.page, "Model selection")
        target = find_target(panel, "ghostship_ai_free_provider_selection_info")
        rows = self.store.wait_for(target["expr"].replace("$provider", ".*"))
        free = [
            {**row["metric"], "value": float(row["value"][1])}
            for row in rows
            if str(row["metric"].get("field") or "").startswith("free_")
        ]
        providers = sorted(
            row["provider"] for row in free if row["field"] == "free_info"
        )
        self.assertEqual(providers, sorted(row[0] for row in FREE_ROWS))
        selection = {row["provider"]: row for row in free if row["field"] == "free_info"}
        self.assertEqual(selection["opencode-go"]["model"], "beam-free")
        self.assertEqual(selection["opencode-go"]["basis"], "published")
        self.assertEqual(selection["google"]["basis"], "inferred")
        self.assertEqual(selection["nvidia"]["basis"], "learning")
        self.assertEqual(selection["requesty"]["basis"], "none")
        counts = {
            (row["provider"], row["state"]): int(row["value"])
            for row in free
            if row["field"] == "free_models"
        }
        self.assertEqual(counts[("opencode-go", "available")], 2)
        self.assertEqual(counts[("requesty", "unavailable")], 7)
        expression = (
            "const rows = "
            + json.dumps(free)
            + ";\n"
            + "const now = "
            + json.dumps(CAPACITY_NOW)
            + ";\n"
            + "console.log(JSON.stringify(helpers.selectionFreeRows(rows, now)));"
        )
        built = run_panel_helper(panel, expression)
        self.assertEqual(built[0], {"group": "Free"})
        self.assertEqual(
            [(row["provider"], row["left"]) for row in built[1:]],
            [(row[0], row[4]) for row in FREE_ROWS],
        )

    def test_a_route_from_an_older_scrape_is_not_shown(self):
        """After a policy edit the table keeps only the newest scrape's rows.

        The row below is 60 s older than the newest scrape: it was still on
        the table while the guard was 90 s wide, although a scrape is 30 s.
        """
        store = VictoriaMetricsFixture()
        self.addCleanup(store.stop)
        if not store.start():
            self.skipTest("VictoriaMetrics did not start")
        panel = section(self.page, "Model selection")
        target = find_target(panel, "ghostship_ai_static_route_info")
        moment = int(time.time())
        lines = [
            f"ghostship_ai_static_route_policy_ok 1 {moment * 1000}",
            f"ghostship_ai_collection_duration_seconds 1 {moment * 1000}",
            f"ghostship_ai_routing_enabled 0 {moment * 1000}",
        ]
        for model, seconds_ago in (("newest", 0), ("one-scrape-older", 60)):
            stamp = (moment - seconds_ago) * 1000
            lines.append(
                f'ghostship_ai_static_route_info{{row="{model}",role="Bulk 1",'
                f'provider="ollama",model="{model}",display_name="{model}",'
                f'used_for="Narrow implementation (1st)"}} 1 {stamp}'
            )
            lines.append(
                f'ghostship_ai_static_route_remaining_ratio{{row="{model}"}} 0.5 {stamp}'
            )
        store.import_text("\n".join(lines) + "\n")
        expression = target["expr"].replace("$provider", ".*")
        deadline = time.time() + 30
        while True:
            result = store.query(expression)
            models = {
                row["metric"].get("model")
                for row in result
                if row["metric"].get("field") == "info"
            }
            if "newest" in models:
                break
            if time.time() > deadline:
                self.fail("the store never answered the newest row")
            time.sleep(0.2)
        self.assertIn("newest", models)
        self.assertNotIn("one-scrape-older", models)


class VictoriaMetricsFixture:
    """A disposable VictoriaMetrics with the review fixture in it."""

    def __init__(self):
        self.binary = os.environ.get("GHOSTSHIP_TEST_VMETRICS") or shutil.which(
            "victoria-metrics"
        )
        self.process = None
        self.directory = None
        self.url = None

    def start(self):
        if not self.binary:
            return False
        self.directory = tempfile.mkdtemp(prefix="ai-usage-page-")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.process = subprocess.Popen(
            [
                self.binary,
                f"-storageDataPath={self.directory}/data",
                f"-httpListenAddr=127.0.0.1:{port}",
                "-retentionPeriod=1d",
                "-search.latencyOffset=0s",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(60):
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=1):
                    return True
            except Exception:
                time.sleep(0.5)
        return False

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.directory:
            shutil.rmtree(self.directory, ignore_errors=True)

    def import_fixture(self, path):
        self.import_text(path.read_text(encoding="utf-8"))

    def import_text(self, text):
        request = urllib.request.Request(
            self.url + "/api/v1/import/prometheus",
            data=text.encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10):
            pass

    def wait_for(self, expression, timeout=30.0):
        """Wait until the store answers with the imported series."""
        deadline = time.time() + timeout
        while True:
            result = self.query(expression)
            if result:
                return result
            if time.time() > deadline:
                raise AssertionError(f"the store never answered {expression!r}")
            time.sleep(0.5)

    def query(self, expression):
        url = self.url + "/api/v1/query?" + urllib.parse.urlencode({"query": expression})
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.load(response)
        return payload["data"]["result"]


@unittest.skipUnless(
    os.environ.get("GHOSTSHIP_TEST_VMETRICS") or shutil.which("victoria-metrics"),
    "Set GHOSTSHIP_TEST_VMETRICS or put victoria-metrics on the path",
)
class WorkedCasesTests(unittest.TestCase):
    """The worked cases, executed against the store the page reads."""

    @classmethod
    def setUpClass(cls):
        cls.page = json.loads(DASHBOARD.read_text(encoding="utf-8"))
        cls.store = VictoriaMetricsFixture()
        if not cls.store.start():
            raise unittest.SkipTest("VictoriaMetrics did not start")

    @classmethod
    def tearDownClass(cls):
        cls.store.stop()

    def setUp(self):
        self.store.import_fixture(FIXTURE)
        # The store answers a moment after the import.
        self.store.wait_for("ghostship_ai_model_winner_position")

    def rows(self, panel, target, key="model"):
        """The rows of a target, keyed by the model or by the provider."""
        expression = target["expr"].replace("$provider", ".*")
        result = self.store.query(expression)
        return {row["metric"].get(key): float(row["value"][1]) for row in result}

    def test_the_share_left_and_the_pace_of_every_route(self):
        """The bar of a route is the share left now, and the pace is the collector's."""
        panel = section(self.page, "Bulk")
        left = self.rows(panel, target_by_field(panel, "left"))
        pace = self.rows(panel, target_by_field(panel, "pace"))
        self.assertAlmostEqual(left["claude-haiku-5-5"], 0.92)
        self.assertAlmostEqual(pace["claude-haiku-5-5"], 0.58)
        self.assertAlmostEqual(left["gemini-3.8-flash"], 0.46)
        self.assertAlmostEqual(pace["gemini-3.8-flash"], 0.0)
        self.assertAlmostEqual(left["grok-4.6"], 0.0)

    def test_the_expected_left_of_the_worked_cases(self):
        """(0.92, +0.58) leaves 34 % expected, (0.09, -0.60) leaves 69 %."""
        for title, model, expected in (
            ("Bulk", "claude-haiku-5-5", 0.34),
            ("Bulk", "gemini-3.8-flash", 0.46),
            ("Frontier", "gpt-6.1-sol", 0.69),
        ):
            panel = section(self.page, title)
            target = target_by_field(panel, "expected")
            rows = self.rows(panel, target)
            self.assertAlmostEqual(rows[model], expected, msg=f"{title} {model}")

    def test_the_pace_of_the_worked_cases_in_points(self):
        """58 points ahead, on pace, and 60 points behind."""
        panel = section(self.page, "Bulk")
        points = self.rows(panel, target_by_field(panel, "points"))
        self.assertEqual(points["claude-haiku-5-5"], 58)
        self.assertEqual(points["gemini-3.8-flash"], 0)
        self.assertEqual(points["grok-4.6"], 0)
        frontier = section(self.page, "Frontier")
        behind = self.rows(frontier, target_by_field(frontier, "points"))
        self.assertEqual(behind["gpt-6.1-sol"], 60)

    def test_the_kind_of_the_pace(self):
        """Three is ahead of the pace, two is on it, one is behind it."""
        panel = section(self.page, "Bulk")
        kind = self.rows(panel, target_by_field(panel, "kind"))
        self.assertEqual(kind["claude-haiku-5-5"], 3)
        self.assertEqual(kind["gemini-3.8-flash"], 2)
        frontier = section(self.page, "Frontier")
        behind = self.rows(frontier, target_by_field(frontier, "kind"))
        self.assertEqual(behind["gpt-6.1-sol"], 1)

    def test_a_spent_route_sinks_to_the_bottom_of_its_table(self):
        """A spent route keeps its place in the table, under the routes that can run."""
        panel = section(self.page, "Bulk")
        order = self.rows(panel, target_by_field(panel, "order"), "model")
        self.assertGreater(order["claude-haiku-5-5"], order["gemini-3.8-flash"])
        self.assertGreater(order["gemini-3.8-flash"], order["grok-4.6"])
        self.assertLess(order["grok-4.6"], 0)

    def test_a_spent_route_comes_after_every_route_that_can_run(self):
        """The spent route of a tier stands below every route that can run.

        The collector gave the exhausted route of the free pool the seventh
        place, above the route that is not a winner at all.
        """
        panel = section(self.page, "Free")
        order = self.rows(panel, target_by_field(panel, "order"))
        spent = self.rows(panel, target_by_field(panel, "out"))
        exhausted = [model for model, flag in spent.items() if flag]
        self.assertTrue(exhausted, "the fixture has a spent route")
        for model in exhausted:
            for other, flag in spent.items():
                if flag:
                    continue
                self.assertLess(order[model], order[other], f"{model} before {other}")

    def test_a_tier_lists_its_winners_and_the_routes_that_are_out(self):
        """Bulk and Free list the ranked winners and the spent routes, nothing else.

        Live, a tier has a few winners and many more members; listing every
        member made the Bulk table about thirty rows long and scroll inside
        its panel. The other members stay in the collapsed evidence rows.
        """
        for title in ("Bulk", "Free"):
            panel = section(self.page, title)
            filters = [
                step for step in panel["transformations"] if step["id"] == "filterByValue"
            ]
            self.assertEqual(len(filters), 1, title)
            options = filters[0]["options"]
            self.assertEqual((options["type"], options["match"]), ("include", "any"))
            self.assertEqual(
                sorted(
                    (rule["fieldName"], rule["config"]["id"], rule["config"]["options"]["value"])
                    for rule in options["filters"]
                ),
                [("out", "greater", 0), ("rank", "greater", 0)],
            )
            rank = self.rows(panel, target_by_field(panel, "rank"))
            out = self.rows(panel, target_by_field(panel, "out"))
            kept = {route for route in rank if rank[route] > 0 or out.get(route, 0) > 0}
            dropped = set(rank) - kept
            if title == "Free":
                # The fixture's available non-winner is dropped; its spent
                # route stays, sunk at the bottom.
                self.assertIn("gpt-oss-120b", dropped)
                self.assertIn("gemma-3-27b", kept)

    def test_a_sunk_route_keeps_no_place(self):
        """A route that cannot be used keeps no place: its rank cell reads '–'."""
        panel = section(self.page, "Free")
        rank = self.rows(panel, target_by_field(panel, "rank"))
        # The exhausted route of the free pool was the seventh winner.
        self.assertEqual(rank["gemma-3-27b"], 0)
        # The routes that can run keep the place of the collector.
        self.assertEqual(rank["qwen3.8-27b"], 3)
        self.assertEqual(rank["llama-4.3-8b"], 5)
        # The cell reads a dash when the route has no place.
        content = panel["options"]["content"]
        self.assertIn("{{#if rank}}{{rank}}{{else}}–{{/if}}", content)

    def test_the_providers_are_read_by_their_name(self):
        """A provider is read by the name the mockup gives it, and an unknown id as it is."""
        expected = {
            "Free": {"nvidia": "NVIDIA", "deepseek": "DeepSeek", "google": "Google",
                     "opencode-go": "OpenCode Go", "fireworks": None},
        }
        for title, names in expected.items():
            panel = section(self.page, title)
            target = provider_name_target(panel)
            rows = self.store.query(target["expr"].replace("$provider", ".*"))
            found = {
                row["metric"]["provider"]: row["metric"].get("providerName")
                for row in rows
            }
            for provider, name in names.items():
                self.assertEqual(found.get(provider), name, f"{title} {provider}")
        # The page reads the name where it shows the provider.
        for title in TIERS:
            content = section(self.page, title)["options"]["content"]
            self.assertIn(
                "{{#if providerName}}{{providerName}}{{else}}{{provider}}{{/if}}",
                content,
                title,
            )

    def test_the_basis_of_a_route_is_the_one_the_collector_publishes(self):
        """The basis of a route is published, inferred, reported or unknown."""
        panel = section(self.page, "Free")
        target = target_by_field(panel, "capacityBasisValue")
        rows = self.store.query(target["expr"].replace("$provider", ".*"))
        bases = {row["metric"]["model"]: row["metric"].get("basis") for row in rows}
        self.assertEqual(bases.get("minimax_minimax-m3.1-flash"), "published")
        self.assertEqual(bases.get("llama-4.3-8b"), "inferred")
        self.assertEqual(bases.get("nemotron-3.5-super-vl"), "unknown")
        self.assertEqual(bases.get("glm-5.3-flash"), "reported")

    def test_a_route_with_unknown_limits_is_flagged_and_never_zero(self):
        """A route with no measured allowance reads unknown, and its share is not a zero."""
        panel = section(self.page, "Free")
        left = self.rows(panel, target_by_field(panel, "left"))
        has_cap = self.rows(panel, target_by_field(panel, "hasCap"))
        self.assertEqual(has_cap["nemotron-3.5-super-vl"], 0)
        self.assertNotEqual(left.get("nemotron-3.5-super-vl"), 0.0)

    def test_a_promotion_route_is_marked_and_has_no_measured_allowance(self):
        """The promotion route is unlimited: it has no allowance and no window."""
        panel = section(self.page, "Bulk")
        promotion = self.rows(panel, target_by_field(panel, "promotion"))
        self.assertEqual(promotion["minimax_minimax-m3.1-flash_free"], 1)
        has_cap = self.rows(panel, target_by_field(panel, "hasCap"))
        self.assertEqual(has_cap["minimax_minimax-m3.1-flash_free"], 0)

    def test_a_route_reserved_for_3d_work_is_marked(self):
        """The reserve of the 3D tier is visible in the tier that holds the route."""
        panel = section(self.page, "Bulk")
        target = target_by_field(panel, "reservedValue")
        rows = self.store.query(target["expr"].replace("$provider", ".*"))
        marks = {row["metric"]["model"]: row["metric"].get("reserveTag") for row in rows}
        self.assertEqual(marks.get("gemini-3.8-flash"), "3d")

    def test_a_route_in_the_free_quality_band_is_marked(self):
        """The band of the free winners is the label the collector publishes."""
        panel = section(self.page, "Free")
        target = target_by_field(panel, "qualityBandValue")
        rows = self.store.query(target["expr"].replace("$provider", ".*"))
        bands = {row["metric"]["model"]: row["metric"].get("qualityBand") for row in rows}
        self.assertEqual(bands.get("minimax_minimax-m3.1-flash"), "true")
        self.assertEqual(bands.get("glm-5.3-flash"), "true")

    def test_the_routing_gauge_reads_one_when_the_collector_publishes_it(self):
        """The chip reads Routing ON when the gauge is one."""
        store = VictoriaMetricsFixture()
        self.addCleanup(store.stop)
        if not store.start():
            self.skipTest("VictoriaMetrics did not start")
        store.import_fixture(FIXTURE_ROUTING_ON)
        store.wait_for("ghostship_ai_routing_enabled")
        header = section(self.page, "")
        target = find_target(header, "ghostship_ai_routing_enabled")
        rows = store.query(target["expr"])
        self.assertEqual([float(row["value"][1]) for row in rows], [1.0])

    def test_the_routing_gauge_reads_zero_when_the_collector_publishes_it(self):
        """The chip reads Routing OFF when the gauge is zero."""
        header = section(self.page, "")
        target = find_target(header, "ghostship_ai_routing_enabled")
        rows = self.store.query(target["expr"])
        self.assertEqual([float(row["value"][1]) for row in rows], [0.0])

    def test_the_capacity_cards_are_read_from_the_collector_s_gauges(self):
        """The panel's own query returns the windows of the live set.

        The query reads every account window gauge in one go, so the rows
        are the windows of the twelve accounts that have one and the
        seventeen accounts that are learning, and the free models of the
        providers that hold a free route.
        """
        panel = section(self.page, "Provider capacity")
        target = find_target(panel, "ghostship_ai_account_window_remaining_ratio")
        rows = self.store.query(target["expr"].replace("$provider", ".*"))
        windows = [
            row for row in rows if row["metric"].get("field") != "free_models"
        ]
        free = [row for row in rows if row["metric"].get("field") == "free_models"]
        self.assertEqual(
            {row["metric"].get("field") for row in windows},
            {
                "left",
                "expected",
                "resetAt",
                "checked",
                "rolling",
                "order",
                "learning",
            },
        )
        accounts = {row["metric"].get("account") for row in windows}
        self.assertEqual(len(accounts), 29)
        self.assertEqual(len(windows), 122)
        # The count of the free routes, by state, for the six providers that
        # hold one.
        self.assertEqual(
            {(row["metric"]["provider"], row["metric"]["state"]) for row in free},
            {
                (provider, state)
                for provider in FREE_MODEL_COUNTS
                for state in ("available", "unavailable")
            },
        )

    def test_the_worked_rows_are_the_rows_the_store_returns(self):
        """The cards of the page are the windows the store holds."""
        panel = section(self.page, "Provider capacity")
        target = find_target(panel, "ghostship_ai_account_window_remaining_ratio")
        rows = self.store.query(target["expr"].replace("$provider", ".*"))
        expression = (
            "const rows = "
            + json.dumps(
                [
                    {**row["metric"], "value": float(row["value"][1])}
                    for row in rows
                ]
            )
            + ";\n"
            + "const now = "
            + json.dumps(CAPACITY_NOW)
            + ";\n"
            + "console.log(JSON.stringify(helpers.capacityCards(rows, now)));"
        )
        cards = run_panel_helper(panel, expression)
        by_account = {card["account"]: card for card in cards}
        session = next(
            window
            for window in by_account["claude"]["windows"]
            if window["label"] == "Session · Claude & GPT"
        )
        self.assertEqual(session["sub"], "▲ 24 ahead · resets in 2h 9m (22 Oct 23:09)")
        monthly = next(
            window
            for window in by_account["opencode-go"]["windows"]
            if window["label"] == "Monthly"
        )
        self.assertEqual(monthly["sub"], "✕ spent · resets in 8.1d (30 Oct 22:34)")


if __name__ == "__main__":
    unittest.main()
