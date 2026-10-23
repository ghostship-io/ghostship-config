"""The static worker table of the runtime policy, as the Providers page reads it.

While the routing switch is off, the owner's policy carries the table that
governs: `worker_routes.entries`, one entry per task and scope, each a list of
routes in the order they are tried. The collector publishes one row per model
of that table, with the role the table gives it, the capacity the routing
snapshot measured for that route, and every entry that names the model.

The live cases are pinned here, with the policy and the capacities of
2026-10-22. A model that is listed twice is one row, and a model that is not
in `worker_routes` has no row at all.
"""

import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COLLECTOR = REPO / "modules/self-hosted/ai-usage/collector"
MODULE = REPO / "modules/self-hosted/ai-usage/default.nix"
FLAKE = REPO / "flake.nix"
CI_INPUTS = REPO / "scripts/ci-private-inputs.py"
if str(COLLECTOR) not in sys.path:
    sys.path.insert(0, str(COLLECTOR))

import main as main_module  # noqa: E402
import static_routes  # noqa: E402
from metrics import ExactLabel  # noqa: E402

NOW = 1_800_000_000.0
# The reset of the codex route, as the snapshot publishes it.
CODEX_RESET = "2026-10-29T17:23:37Z"
CODEX_RESET_EPOCH = datetime(
    2026, 10, 29, 17, 23, 37, tzinfo=timezone.utc
).timestamp()

# The live table, in the order the policy carries it. The display order is
# the order of the page: the bulk routes by their place in the bulk entry,
# then the large route, then the deploy routes, then a research-only route.
POLICY = {
    "schema_version": 1,
    "worker_routes": {
        "entries": [
            {
                "task_type": "implementation",
                "scope": "narrow",
                "routes": [
                    {"instance_id": "opencode", "model": "ollama-cloud/minimax-m3.1-flash"},
                    {
                        "instance_id": "opencode",
                        "model": "ollama-cloud/deepseek-v4.1-flash:1017",
                    },
                ],
            },
            {
                "task_type": "research",
                "scope": "narrow",
                "routes": [
                    {
                        "instance_id": "opencode",
                        "model": "ollama-cloud/deepseek-v4.1-flash:1017",
                    },
                    {"instance_id": "opencode", "model": "ollama-cloud/minimax-m3.1-flash"},
                    {"instance_id": "opencode", "model": "opencode-go/beam-free"},
                ],
            },
            {
                "task_type": "activation",
                "scope": "narrow",
                "routes": [
                    {"instance_id": "opencode", "model": "opencode-go/beam-free"},
                    {"instance_id": "opencode", "model": "ollama-cloud/beam"},
                ],
            },
            {
                "task_type": "implementation",
                "scope": "large",
                "routes": [{"instance_id": "codex", "model": "gpt-6.1-sol"}],
            },
        ]
    },
}

# The live candidate rows the snapshot carries. The candidate that is not in
# the table is the control: it must not produce a row.
SNAPSHOT = {
    "candidates": [
        {
            "provider": "ollama",
            "model": "minimax-m3.1-flash",
            "capacity": {
                "remaining_ratio": 0.4129,
                "pace_delta": 0.0512,
                "capacity_binding": {"reset_at": "2026-10-26T00:00:00Z"},
            },
        },
        {
            "provider": "ollama",
            "model": "deepseek-v4.1-flash:1017",
            "capacity": {
                "remaining_ratio": 0.5,
                "pace_delta": None,
                "capacity_binding": {"reset_at": None},
            },
        },
        {
            "provider": "codex",
            "model": "gpt-6.1-sol",
            "capacity": {
                "remaining_ratio": 0.99,
                "pace_delta": 0.1234,
                "capacity_binding": {"reset_at": CODEX_RESET},
            },
        },
        {
            "provider": "opencode-go",
            "model": "beam-free",
            "capacity": {
                "remaining_ratio": 1.0,
                "pace_delta": None,
                "capacity_binding": {"reset_at": "2026-10-23T01:36:00Z"},
            },
        },
        {
            "provider": "opencode",
            "model": "not-in-the-table",
            "capacity": {"remaining_ratio": 0.3},
        },
    ]
}

DISPLAY_NAMES = {
    ("ollama", "minimax-m3.1-flash"): "MiniMax M3.1 Flash",
    ("ollama", "deepseek-v4.1-flash:1017"): "DeepSeek V4.1 Flash 1017",
    ("codex", "gpt-6.1-sol"): "GPT-6.1 Sol",
    ("opencode-go", "beam-free"): "Beam Free",
}


def write_policy(test, document=POLICY, text=None):
    """A policy file for one test, under its own temporary directory."""
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "runtime-policy.json"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def by_row(samples, name):
    return {
        labels.get("row"): (labels, value)
        for sample_name, labels, value in samples
        if sample_name == name
    }


def info_rows(samples):
    return {
        labels["row"]: labels
        for name, labels, _value in samples
        if name == "ghostship_ai_static_route_info"
    }


# The table of a route whose model id carries a slash. The name of the
# model is published with the model label the exposition format allows, so
# the id of the series is not the id of the route.
NAME_POLICY = {
    "schema_version": 1,
    "worker_routes": {
        "entries": [
            {
                "task_type": "implementation",
                "scope": "narrow",
                "routes": [
                    {"instance_id": "groq", "model": "qwen/qwen3.8-27b"},
                    {"instance_id": "kilo", "model": "nvidia/nemotron-3.5-super-vl:free"},
                ],
            }
        ]
    },
}

# The names the collector publishes for those models.
PUBLISHED_NAMES = [
    (
        "ghostship_ai_model_info",
        {
            "provider": "groq",
            "model": "qwen_qwen3.8-27b",
            "name": ExactLabel("Qwen3.8 27B"),
        },
        1.0,
    ),
]


def published_names(samples):
    """The display names, built the way the collector builds them.

    The collector reads the name of every model from the series it
    publishes for the model, and keys it by the provider and the model
    label of that series.
    """
    names = {}
    for name, labels, _value in samples:
        if name != "ghostship_ai_model_info":
            continue
        provider = str(labels.get("provider") or "")
        model = str(labels.get("model") or "")
        text = str(labels.get("name") or "")
        if provider and model and text:
            names[(provider, model)] = text
    return names


class StaticRouteDisplayNameTests(unittest.TestCase):
    """The name of the model a static route names.

    The name is published with the model label the exposition format
    allows, and the id of a route is the id the provider gave. A route
    whose model id carries a slash carries the name the collector
    published for that model.
    """

    def samples(self, names=None):
        return static_routes.samples(
            write_policy(self, document=NAME_POLICY),
            {},
            published_names(PUBLISHED_NAMES) if names is None else names,
        )

    def test_a_route_whose_model_id_has_a_slash_carries_its_published_name(self):
        rows = info_rows(self.samples())
        self.assertEqual(rows["1"]["display_name"], "Qwen3.8 27B")

    def test_a_route_without_a_published_name_falls_back_to_its_raw_id(self):
        """Kilo's route names a model that is published nowhere."""
        rows = info_rows(self.samples())
        self.assertEqual(
            rows["2"]["display_name"], "nvidia/nemotron-3.5-super-vl:free"
        )

    def test_the_other_labels_of_the_row_are_unchanged(self):
        """The name is the only label the fix touches."""
        rows = info_rows(self.samples())
        self.assertEqual(rows["1"]["provider"], "groq")
        self.assertEqual(rows["1"]["model"], "qwen/qwen3.8-27b")
        self.assertEqual(rows["1"]["role"], "Bulk 1")
        self.assertEqual(rows["1"]["used_for"], "Narrow implementation (1st)")


class StaticRouteTableTests(unittest.TestCase):
    def test_the_table_is_one_row_per_model_in_display_order(self):
        """The page's five rows: bulk 1, bulk 2, large, and the two deploys."""
        samples = static_routes.samples(write_policy(self), SNAPSHOT, DISPLAY_NAMES)
        rows = info_rows(samples)
        table = [
            (
                labels["row"],
                labels["role"],
                labels["provider"],
                labels["model"],
                labels["used_for"],
            )
            for labels in sorted(rows.values(), key=lambda labels: int(labels["row"]))
        ]
        self.assertEqual(
            table,
            [
                (
                    "1",
                    "Bulk 1",
                    "ollama",
                    "minimax-m3.1-flash",
                    "Narrow implementation (1st), Research (2nd)",
                ),
                (
                    "2",
                    "Bulk 2",
                    "ollama",
                    "deepseek-v4.1-flash:1017",
                    "Narrow implementation (2nd), Research (1st)",
                ),
                (
                    "3",
                    "Large",
                    "codex",
                    "gpt-6.1-sol",
                    "Large implementation (1st)",
                ),
                (
                    "4",
                    "Deploys",
                    "opencode-go",
                    "beam-free",
                    "Deploys (1st), Research (3rd)",
                ),
                ("5", "Deploys", "ollama", "beam", "Deploys (2nd)"),
            ],
        )

    def test_the_columns_run_from_one_without_a_gap(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        rows = info_rows(samples)
        self.assertEqual(sorted(int(row) for row in rows), [1, 2, 3, 4, 5])

    def test_a_model_listed_twice_has_one_row(self):
        """DeepSeek is in the bulk entry and in the research entry."""
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        models = [labels["model"] for labels in info_rows(samples).values()]
        self.assertEqual(models.count("deepseek-v4.1-flash:1017"), 1)

    def test_a_model_outside_the_worker_routes_has_no_row(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        models = {labels["model"] for labels in info_rows(samples).values()}
        self.assertNotIn("not-in-the-table", models)

    def test_the_remaining_share_comes_from_the_route_s_candidate(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        remaining = by_row(samples, "ghostship_ai_static_route_remaining_ratio")
        self.assertAlmostEqual(remaining["1"][1], 0.4129)
        self.assertAlmostEqual(remaining["3"][1], 0.99)
        self.assertAlmostEqual(remaining["4"][1], 1.0)

    def test_a_route_without_a_candidate_keeps_its_info_row_and_no_capacity(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        self.assertIn("5", info_rows(samples))
        for name in (
            "ghostship_ai_static_route_remaining_ratio",
            "ghostship_ai_static_route_paced_availability",
            "ghostship_ai_static_route_reset_timestamp_seconds",
        ):
            self.assertNotIn("5", by_row(samples, name))

    def test_the_paced_availability_is_the_pace_delta(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        pace = by_row(samples, "ghostship_ai_static_route_paced_availability")
        self.assertAlmostEqual(pace["1"][1], 0.0512)

    def test_a_promotion_without_a_pace_has_no_pace_series(self):
        """Beam Free is published as unlimited for now, and carries no pace."""
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        pace = by_row(samples, "ghostship_ai_static_route_paced_availability")
        self.assertNotIn("4", pace)
        self.assertIn("4", by_row(samples, "ghostship_ai_static_route_remaining_ratio"))

    def test_the_reset_is_the_binding_reset_of_the_candidate(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        reset = by_row(samples, "ghostship_ai_static_route_reset_timestamp_seconds")
        self.assertAlmostEqual(reset["3"][1], CODEX_RESET_EPOCH)

    def test_the_info_carries_the_existing_display_name(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT, DISPLAY_NAMES)
        rows = info_rows(samples)
        self.assertEqual(rows["1"]["display_name"], "MiniMax M3.1 Flash")
        self.assertEqual(rows["3"]["display_name"], "GPT-6.1 Sol")

    def test_a_model_without_a_display_name_falls_back_to_its_id(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT, DISPLAY_NAMES)
        self.assertEqual(info_rows(samples)["5"]["display_name"], "beam")

    def test_a_readable_policy_is_ok(self):
        samples = static_routes.samples(write_policy(self), SNAPSHOT)
        ok = by_row(samples, "ghostship_ai_static_route_policy_ok")
        self.assertEqual(ok[None][1], 1.0)

    def test_a_missing_policy_publishes_no_rows_and_is_not_ok(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        missing = str(Path(directory.name) / "absent.json")
        samples = static_routes.samples(missing, SNAPSHOT)
        self.assertEqual(info_rows(samples), {})
        self.assertEqual(
            by_row(samples, "ghostship_ai_static_route_policy_ok")[None][1], 0.0
        )

    def test_an_unreadable_policy_publishes_no_rows_and_is_not_ok(self):
        samples = static_routes.samples(write_policy(self, text="{not json"), SNAPSHOT)
        self.assertEqual(info_rows(samples), {})
        self.assertEqual(
            by_row(samples, "ghostship_ai_static_route_policy_ok")[None][1], 0.0
        )


class StaticRouteWiringTests(unittest.TestCase):
    def test_the_collector_renders_the_published_name_of_a_route(self):
        """The name is read from the series the collector publishes."""
        from metrics import SourceResult

        path = write_policy(self, document=NAME_POLICY)
        result = SourceResult(
            source="t3",
            status="ok",
            metrics=list(PUBLISHED_NAMES),
        )
        text = main_module.render(
            [result], [], NOW, 0.0, {}, runtime_policy=path
        )
        rows = [
            line
            for line in text.splitlines()
            if line.startswith("ghostship_ai_static_route_info{")
        ]
        self.assertEqual(len(rows), 2)
        by_provider = {
            re.search(r'provider="([^"]+)"', line).group(1): line for line in rows
        }
        self.assertIn('display_name="Qwen3.8 27B"', by_provider["groq"])
        self.assertIn('model="qwen_qwen3.8-27b"', by_provider["groq"])
        self.assertIn(
            'display_name="nvidia/nemotron-3.5-super-vl:free"', by_provider["kilo"]
        )

    def test_the_collector_renders_the_table(self):
        path = write_policy(self)
        text = main_module.render(
            [], [], NOW, 0.0, SNAPSHOT, runtime_policy=path
        )
        rows = [
            line
            for line in text.splitlines()
            if line.startswith("ghostship_ai_static_route_info{")
        ]
        self.assertEqual(len(rows), 5)
        by_number = {
            re.search(r'row="([0-9]+)"', line).group(1): line for line in rows
        }
        self.assertIn(
            'used_for="Narrow implementation (1st), Research (2nd)"',
            by_number["1"],
        )
        self.assertIn('role="Bulk 1"', by_number["1"])
        self.assertIn("ghostship_ai_static_route_policy_ok 1", text)

    def test_the_collector_still_renders_when_the_policy_is_missing(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        text = main_module.render(
            [],
            [],
            NOW,
            0.0,
            SNAPSHOT,
            runtime_policy=str(Path(directory.name) / "absent.json"),
        )
        self.assertNotIn("ghostship_ai_static_route_info{", text)
        self.assertIn("ghostship_ai_static_route_policy_ok 0", text)
        self.assertIn("ghostship_ai_collection_timestamp_seconds", text)

    def test_the_unit_passes_the_policy_file(self):
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("--runtime-policy", module)
        self.assertIn("args.inputs", module)
        self.assertIn("ghostship-agent-policy", module)
        self.assertIn("config/agents/runtime-policy.json", module)

    def test_the_policy_has_its_own_flake_input(self):
        flake = FLAKE.read_text(encoding="utf-8")
        self.assertRegex(
            flake,
            r"ghostship-agent-policy\s*=\s*\{[^}]*flake\s*=\s*false;",
        )
        # The input is pinned to one exact revision, and the lock holds that
        # revision: a branch name or a stale lock would let the policy drift.
        pinned = re.search(
            r"ghostship-agent-policy\s*=\s*\{[^}]*url\s*=\s*\"github:ghostship-io/"
            r"ghostship-agent/([0-9a-f]{40})\"",
            flake,
        )
        self.assertIsNotNone(pinned, "the policy input names no exact revision")
        lock = json.loads((FLAKE.parent / "flake.lock").read_text(encoding="utf-8"))
        self.assertEqual(
            lock["nodes"]["ghostship-agent-policy"]["locked"]["rev"], pinned.group(1)
        )

    def test_ci_imports_the_policy_input_with_the_agent_key(self):
        script = CI_INPUTS.read_text(encoding="utf-8")
        self.assertRegex(
            script,
            r"'ghostship-agent-policy':\s*\{\s*'repo':\s*'ghostship-agent',\s*'key':\s*'agent'",
        )

    def test_ci_working_paths_are_named_after_the_input(self):
        """Both inputs share one read key, so one may not reuse the other's paths."""
        script = CI_INPUTS.read_text(encoding="utf-8")
        self.assertIn("'checkout-' + name", script)
        self.assertIn("'source-' + name", script)
        self.assertIn("name + '.tar'", script)


if __name__ == "__main__":
    unittest.main()
