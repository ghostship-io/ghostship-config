"""The Providers page of the AI usage dashboard.

The page is five sections, each one a Business Text panel, and the evidence
below them in collapsed rows. The tests here pin the contract the page has
with the owner: the order of a tier is the collector's own winner position,
the fill of a bar is the share left now, the line in the bar is the share the
window expects to be left now, and the pace reads the difference between the
two.

The queries are executed against the committed review fixture, so the worked
cases are the numbers the store returns and not a copy of them.
"""
import json
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "modules/self-hosted/siem/dashboards/ai-usage.json"
FIXTURE = ROOT / "tests/fixtures/ai-usage/providers-review.prom"
FIXTURE_ROUTING_ON = ROOT / "tests/fixtures/ai-usage/providers-review-routing-on.prom"

# The sections of the page, in the order the owner approved.
SECTIONS = ("Bulk", "Free", "Frontier", "3D", "Providers")
TIERS = {"Bulk": "bulk", "Free": "free", "Frontier": "frontier", "3D": "3d"}

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
        script = (
            "const helpers = {};\n"
            "const handlebars = { registerHelper: (name, fn) => { helpers[name] = fn; } };\n"
            + helpers
            + "\nconsole.log(helpers.utcStamp(String(Date.UTC(2026, 9, 22, 19, 5, 0))));"
            + "\nconsole.log(JSON.stringify(helpers.utcStamp('not a time')));"
        )
        # A viewer far from UTC: the helper must not use the local zone.
        env = dict(os.environ, TZ="Etc/GMT+10")
        result = subprocess.run(
            [node, "-e", script], capture_output=True, text=True, env=env, check=True
        )
        self.assertEqual(result.stdout.split("\n")[:2], ["22 Oct 19:05", '""'])

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
            panel = section(self.page, title)
            sorts = [t for t in panel.get("transformations") or [] if t["id"] == "sortBy"]
            self.assertEqual(len(sorts), 1, title)
            self.assertEqual(sorts[0]["options"]["sort"][0]["field"], "order", title)
            self.assertTrue(sorts[0]["options"]["sort"][0]["desc"], title)

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
        """The chip is the collector's routing state, not a fixed text."""
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
            if panel.get("id") == 200:
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
        for title in list(TIERS) + ["Providers"]:
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
        for title in list(TIERS) + ["Providers"]:
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
        for title in list(TIERS) + ["Providers"]:
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
        for title in list(TIERS) + ["Providers"]:
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
        for title in list(TIERS) + ["Providers"]:
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
        for title in list(TIERS) + ["Providers"]:
            content = section(self.page, title)["options"]["content"]
            self.assertIn('class="unk" title="', content, title)

    def test_every_provider_is_read_by_its_name(self):
        """A provider is read by the name the mockup gives it."""
        for title in list(TIERS) + ["Providers"]:
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
        request = urllib.request.Request(
            self.url + "/api/v1/import/prometheus",
            data=path.read_bytes(),
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

    def test_a_spent_provider_comes_after_every_provider_that_can_run(self):
        """The spent account of a provider stands below the accounts that can run."""
        panel = section(self.page, "Providers")
        order = self.rows(panel, target_by_field(panel, "order"), "provider")
        spent = self.rows(panel, target_by_field(panel, "out"), "provider")
        exhausted = [provider for provider, flag in spent.items() if flag]
        self.assertTrue(exhausted, "the fixture has a spent account")
        for provider in exhausted:
            for other, flag in spent.items():
                if flag:
                    continue
                self.assertLess(order[provider], order[other], f"{provider} before {other}")

    def test_an_unknown_provider_comes_after_every_provider_with_a_reading(self):
        """A provider with no capacity reading stands below every provider with one.

        The fixture's google publishes an entitlement reset and no capacity
        window and no coverage series; it still reads "Limits unknown", and
        it must still sort below the providers that have a reading.
        """
        panel = section(self.page, "Providers")
        order = self.rows(panel, target_by_field(panel, "order"), "provider")
        has_cap = self.rows(panel, target_by_field(panel, "hasCap"), "provider")
        unknown = [p for p in order if not has_cap.get(p)]
        self.assertIn("google", unknown)
        for provider in unknown:
            for other, flag in has_cap.items():
                if flag:
                    self.assertLess(order[provider], order[other], f"{provider} before {other}")

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
            "Providers": {"claude": "Claude", "nvidia": "NVIDIA", "google": "Google",
                          "openrouter": "OpenRouter", "fireworks": None},
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
        for title in list(TIERS) + ["Providers"]:
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

    def test_the_providers_are_sorted_by_paced_availability_with_the_spent_last(self):
        """The lowest window decides, and a spent or unknown account comes last."""
        panel = section(self.page, "Providers")
        order = self.rows(panel, target_by_field(panel, "order"), "provider")
        self.assertGreater(order["claude"], order["antigravity"])
        self.assertGreater(order["antigravity"], order["codex"])
        self.assertLess(order["ollama"], order["codex"])
        self.assertLess(order["cursor"], order["ollama"])

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


if __name__ == "__main__":
    unittest.main()
