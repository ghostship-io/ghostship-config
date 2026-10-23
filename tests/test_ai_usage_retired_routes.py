"""The retired routes of the AI usage collector.

A provider that retires a model does not serve it again. The collector
reads that out of the T3 Code state, marks the route unavailable with the
reason `model_retired`, keeps it out of every tier, and remembers the
retirement in its own state file, so the retirement outlives the window of
the failure that reported it. A later successful run of the route clears
it: the provider serves the model again.

Every test here is synthetic: the state database is built in a temporary
directory, the error texts are the ones a provider writes, and no host is
read.
"""

import contextlib
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage/collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import catalog as catalog_module  # noqa: E402
import main  # noqa: E402
import runtime_state  # noqa: E402
from metrics import SourceResult  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86_400.0
HOUR = 3_600.0

# The provider that serves the free Go routes, and the two models of it the
# collector knows: the free route that was retired, and the other model of
# the same provider, which the retirement does not touch.
OFFERED = (
    ("opencode-go", "minimax-m3.1-flash-free"),
    ("opencode-go", "glm-5.3"),
)

# The public catalog of the two providers the tests use. The Go free route
# is priced at zero, so it is a dedicated free route, and the OpenRouter
# free route is priced at zero too.
CATALOG = {
    "opencode-go": {
        "models": {
            "minimax-m3.1-flash-free": {
                "name": "MiniMax M3.1 Flash Free",
                "family": "minimax",
                "release_date": "2026-10-01",
                "cost": {"input": 0.0, "output": 0.0},
            },
            "glm-5.3": {
                "name": "GLM 5.3",
                "family": "glm",
                "release_date": "2026-10-01",
                "cost": {"input": 1.0, "output": 2.0},
            },
        }
    },
    "openrouter": {
        "models": {
            "minimax/minimax-m3.1-flash:free": {
                "name": "MiniMax M3.1 Flash (free)",
                "family": "minimax",
                "release_date": "2026-10-01",
                "cost": {"input": 0.0, "output": 0.0},
            }
        }
    },
}


def stamp(offset: float) -> str:
    """An ISO timestamp `offset` seconds before the moment of the tests."""
    return (
        datetime.fromtimestamp(NOW - offset, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def aa_cache(models) -> dict:
    """A measured Artificial Analysis cache for the given models."""
    records = []
    for provider, model in models:
        records.append(
            {
                "id": f"id-{provider}-{model}",
                "slug": model,
                "model": model,
                "release_date": "2026-01-20",
                "indices": {"intelligence_index": 80.0},
                "cost_per_task": 0.2,
                "median_performance": 100.0,
                "prices": {},
            }
        )
    return {
        "status": "ok",
        "index_version": "4.3",
        "fetched_at": "2026-01-20T00:00:00Z",
        "fetched_at_epoch": NOW,
        "records": records,
    }


def build_state(path: Path, *, runs=(), sessions=()) -> Path:
    """A T3 Code state database with the given runs and sessions."""
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE orchestration_v2_projection_run_attempts "
        "(attempt_id TEXT, thread_id TEXT, run_id TEXT, attempt_ordinal INTEGER, "
        "root_node_id TEXT, provider TEXT, provider_thread_id TEXT, "
        "provider_turn_id TEXT, status TEXT, payload_json TEXT, "
        "provider_instance_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE orchestration_v2_projection_runs "
        "(run_id TEXT, thread_id TEXT, ordinal INTEGER, provider TEXT, "
        "provider_thread_id TEXT, status TEXT, requested_at TEXT, "
        "completed_at TEXT, payload_json TEXT, provider_instance_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE projection_thread_sessions "
        "(thread_id TEXT, status TEXT, provider_name TEXT, "
        "provider_session_id TEXT, provider_thread_id TEXT, active_turn_id TEXT, "
        "last_error TEXT, updated_at TEXT, runtime_mode TEXT, "
        "provider_instance_id TEXT)"
    )
    connection.execute(
        "CREATE TABLE provider_session_runtime "
        "(thread_id TEXT, provider_name TEXT, adapter_key TEXT, "
        "runtime_mode TEXT, status TEXT, last_seen_at TEXT, "
        "resume_cursor_json TEXT, runtime_payload_json TEXT, "
        "provider_instance_id TEXT)"
    )
    for index, run in enumerate(runs):
        instance = run.get("instance", "opencode")
        completed = run.get("completed_at") or stamp(HOUR)
        connection.execute(
            "INSERT INTO orchestration_v2_projection_run_attempts VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"attempt-{index}",
                run.get("thread_id", "thread-1"),
                run["run_id"],
                1,
                "root",
                "opencode",
                "provider-thread",
                None,
                run.get("status", "failed"),
                json.dumps(
                    {
                        "startedAt": completed,
                        "completedAt": completed,
                        "model": run.get("model", ""),
                    }
                ),
                instance,
            ),
        )
        connection.execute(
            "INSERT INTO orchestration_v2_projection_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run["run_id"],
                run.get("thread_id", "thread-1"),
                index,
                "opencode",
                "provider-thread",
                run.get("status", "failed"),
                completed,
                completed,
                json.dumps(
                    {
                        "modelSelection": {
                            "instanceId": instance,
                            "model": run.get("model", ""),
                        }
                    }
                ),
                instance,
            ),
        )
    for session in sessions:
        connection.execute(
            "INSERT INTO projection_thread_sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                session.get("thread_id", "thread-1"),
                "stopped",
                "opencode",
                "session",
                "provider-thread",
                None,
                session.get("last_error", ""),
                session.get("updated_at") or stamp(HOUR),
                "full-access",
                session.get("instance", "opencode"),
            ),
        )
    connection.commit()
    connection.close()
    return path


@contextlib.contextmanager
def faked_sources(models):
    """The sources of the collector, faked: only the state is real."""
    offered = list(models)

    def fake_t3(moment, catalog, context):
        context["native_models"] = {
            (provider, model): {
                "providerInstance": "opencode",
                "modelId": model,
                "options": [],
            }
            for provider, model in offered
        }
        context["offered_models"] = list(offered)
        return [
            SourceResult(
                source="t3", status="ok", reason="ok", observed_at=moment, metrics=[]
            )
        ]

    def empty(*args, **kwargs):
        return SourceResult(
            source="fake", status="ok", reason="ok", observed_at=NOW, metrics=[]
        )

    originals = {
        "collect_t3": main.collect_t3,
        "grok": main.providers_module.read_grok,
        "go": main.providers_module.read_opencode_go,
        "antigravity": main.providers_module.read_antigravity,
        "openrouter": main.providers_module.read_openrouter,
        "ollama": main.providers_module.read_ollama,
        "pool": main.pool_module.collect,
    }
    main.collect_t3 = fake_t3
    main.providers_module.read_grok = empty
    main.providers_module.read_opencode_go = empty
    main.providers_module.read_antigravity = empty
    main.providers_module.read_openrouter = empty
    main.providers_module.read_ollama = empty
    main.pool_module.collect = lambda *a, **k: []
    try:
        yield
    finally:
        main.collect_t3 = originals["collect_t3"]
        main.providers_module.read_grok = originals["grok"]
        main.providers_module.read_opencode_go = originals["go"]
        main.providers_module.read_antigravity = originals["antigravity"]
        main.providers_module.read_openrouter = originals["openrouter"]
        main.providers_module.read_ollama = originals["ollama"]
        main.pool_module.collect = originals["pool"]


def sample_of(samples, name, **labels):
    """The value of one published sample, or None when it is not published."""
    for entry in samples:
        if entry[0] != name:
            continue
        found = entry[1]
        if all(
            str(found.get(key, "")) == str(value) for key, value in labels.items()
        ):
            return entry[2]
    return None


class Harness:
    """The collector, with its sources faked and a synthetic T3 state."""

    def __init__(self, directory: Path, models=OFFERED):
        self.models = list(models)
        self.home = directory / "home"
        self.home.mkdir(parents=True, exist_ok=True)
        self.state_path = directory / "state.json"
        self.catalog_path = directory / "models.json"
        self.catalog_path.write_text(json.dumps(CATALOG), encoding="utf-8")
        self.database = directory / "statev2.sqlite"

    def write_state(self, *, runs=(), sessions=()) -> Path:
        """The T3 Code state database of this collection."""
        if self.database.exists():
            self.database.unlink()
        return build_state(self.database, runs=runs, sessions=sessions)

    def collect(self, *, now=NOW):
        """One collection: the published samples and the routing snapshot."""
        with faked_sources(self.models):
            results, extra, context = main.collect(
                now,
                t3_home=str(self.home),
                state_path=str(self.state_path),
                t3_state=str(self.database),
                catalog_path=str(self.catalog_path),
                aa_cache=aa_cache(self.models),
                aa_3d_cache={"status": "missing"},
            )
        snapshot = main.build_snapshot(
            results,
            context.get("ranked") or [],
            context,
            now,
            aa_cache=aa_cache(self.models),
            aa_3d_cache={"status": "missing"},
            catalog=catalog_module.Catalog.load(str(self.catalog_path)),
            free_models=context.get("free_models") or set(),
            promo_models=context.get("promo_models") or set(),
        )
        return extra, snapshot

    def state(self) -> dict:
        """The collector's own state file."""
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))


class RetirementReasonTests(unittest.TestCase):
    """The reason code of a failure that names a retirement."""

    def _failures(self, error: str, *, model: str, instance: str = "opencode"):
        with tempfile.TemporaryDirectory() as folder:
            path = build_state(
                Path(folder) / "statev2.sqlite",
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": instance,
                        "model": model,
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": error,
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            return runtime_state.read_failures(path, NOW)

    def test_a_deprecated_model_is_a_retirement(self):
        failures = self._failures(
            "Model minimax-m3.1-flash-free has been deprecated",
            model="opencode-go/minimax-m3.1-flash-free",
        )
        self.assertEqual(len(failures), 1)
        failure = failures[0]
        self.assertEqual(failure["reason"], "model_retired")
        self.assertEqual(failure["scope"], "model")
        self.assertEqual(failure["target"], "opencode-go/minimax-m3.1-flash-free")
        # The retirement names the route, the provider and the model.
        self.assertEqual(failure["provider"], "opencode-go")
        self.assertEqual(failure["model"], "minimax-m3.1-flash-free")

    def test_a_free_variant_that_was_retired_is_a_retirement(self):
        failures = self._failures(
            "The free launch period for MiniMax M3.1 Flash ended on Oct 22, "
            "2026. The `:free` variant has been retired and is no longer "
            "served.",
            model="openrouter/minimax/minimax-m3.1-flash:free",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "model_retired")
        self.assertEqual(failures[0]["provider"], "openrouter")
        self.assertEqual(failures[0]["model"], "minimax/minimax-m3.1-flash:free")

    def test_a_model_that_reached_the_end_of_its_life_is_a_retirement(self):
        failures = self._failures(
            "The model minimax-m3.1-flash-free reached its end of life.",
            model="opencode-go/minimax-m3.1-flash-free",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "model_retired")

    def test_an_unavailable_endpoint_is_not_a_retirement(self):
        # The provider refused the request, but it did not retire the model:
        # the failure is the route's, as it was before.
        failures = self._failures(
            "Upstream request failed: Endpoint is unavailable.",
            model="opencode-go/minimax-m3.1-flash-free",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "provider_error")
        self.assertEqual(failures[0]["scope"], "route")

    def test_a_bad_request_is_a_refusal_as_before(self):
        failures = self._failures(
            "Bad Request: the model is not allowed.",
            model="opencode-go/minimax-m3.1-flash-free",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "model_refused")
        self.assertEqual(failures[0]["scope"], "model")

    def test_a_usage_limit_is_an_account_failure_as_before(self):
        failures = self._failures(
            "Go usage limit exceeded",
            model="opencode-go/minimax-m3.1-flash-free",
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "account_usage_limit")
        self.assertEqual(failures[0]["scope"], "account")
        self.assertEqual(failures[0]["target"], "opencode-go")


class RetiredRouteTests(unittest.TestCase):
    """A retired route is unavailable, and it holds no tier."""

    def test_a_retired_route_is_unavailable_and_holds_no_tier(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            samples, snapshot = harness.collect()

            # The route is not available, and the reason is the code.
            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                ),
                0.0,
            )
            self.assertIsNone(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="",
                )
            )
            # The route holds no tier, not the bulk tier and not the free
            # tier, whatever window it has.
            for tier in ("worker", "free", "orchestrator", "3d"):
                self.assertNotIn(
                    "opencode-go:minimax-m3.1-flash-free", snapshot["tiers"][tier]
                )
                self.assertNotIn(
                    "opencode-go:minimax-m3.1-flash-free",
                    [row["key"] for row in snapshot["tier_winners"][tier]],
                )
            # The candidate says why it is not available.
            row = [
                candidate
                for candidate in snapshot["candidates"]
                if candidate["model"] == "minimax-m3.1-flash-free"
            ][0]
            self.assertEqual(row["availability"]["state"], "unavailable")
            self.assertEqual(row["availability"]["reason"], "model_retired")

    def test_the_other_model_of_the_provider_is_unaffected(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            samples, snapshot = harness.collect()

            # The other model of the same provider is available, and it is
            # not retired.
            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="glm-5.3",
                    reason="model_retired",
                ),
                None,
            )
            available = [
                entry
                for entry in samples
                if entry[0] == "ghostship_ai_model_available"
                and entry[1].get("model") == "glm-5.3"
            ]
            self.assertTrue(available)
            self.assertEqual(available[0][2], 1.0)
            self.assertIn("opencode-go:glm-5.3", snapshot["tiers"]["worker"])

    def test_a_retired_openrouter_route_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(
                Path(folder), models=(("openrouter", "minimax/minimax-m3.1-flash:free"),)
            )
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "openrouter/minimax/minimax-m3.1-flash:free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": (
                            "The free launch period for MiniMax M3.1 Flash ended "
                            "on Oct 22, 2026. The `:free` variant has been retired."
                        ),
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            samples, snapshot = harness.collect()

            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="openrouter",
                    model="minimax_minimax-m3.1-flash:free",
                    reason="model_retired",
                ),
                0.0,
            )
            self.assertNotIn(
                "openrouter:minimax/minimax-m3.1-flash:free",
                snapshot["tiers"]["free"],
            )

    def test_the_retirement_is_remembered_in_the_state_file(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            harness.collect()
            state = harness.state()
        record = state["opencode-go/minimax-m3.1-flash-free"]["retired"]
        self.assertEqual(record["provider"], "opencode-go")
        self.assertEqual(record["model"], "minimax-m3.1-flash-free")
        self.assertEqual(record["route"], "opencode-go/minimax-m3.1-flash-free")
        self.assertTrue(record["first_seen"])

    def test_the_retirement_survives_the_next_run(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            harness.collect()
            # The next run reads a state that reports nothing new.
            harness.write_state()
            samples, snapshot = harness.collect()

            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                ),
                0.0,
            )
            self.assertNotIn(
                "opencode-go/minimax-m3.1-flash-free", snapshot["tiers"]["free"]
            )

    def test_the_retirement_survives_the_window_of_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            harness.collect()
            # The failure that reported the retirement is now older than the
            # window of a failure, and the state reports nothing.
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(2 * DAY),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(2 * DAY),
                    }
                ],
            )
            samples, snapshot = harness.collect()

            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                ),
                0.0,
            )
            self.assertNotIn(
                "opencode-go/minimax-m3.1-flash-free", snapshot["tiers"]["worker"]
            )

    def test_a_later_success_makes_the_route_available_again(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(2 * HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(2 * HOUR),
                    }
                ],
            )
            harness.collect()
            # The provider serves the route again.
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(2 * HOUR),
                    },
                    {
                        "run_id": "run-2",
                        "thread_id": "thread-2",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "completed",
                        "completed_at": stamp(HOUR),
                    },
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Model minimax-m3.1-flash-free has been deprecated",
                        "updated_at": stamp(2 * HOUR),
                    }
                ],
            )
            samples, snapshot = harness.collect()

            self.assertIsNone(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                )
            )
            self.assertEqual(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="",
                ),
                1.0,
            )
            # The state file forgets the retirement too.
            state = harness.state()
            self.assertNotIn(
                "retired", state.get("opencode-go/minimax-m3.1-flash-free", {})
            )

    def test_a_failure_that_is_not_a_retirement_retires_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = Harness(Path(folder))
            harness.write_state(
                runs=[
                    {
                        "run_id": "run-1",
                        "thread_id": "thread-1",
                        "instance": "opencode",
                        "model": "opencode-go/minimax-m3.1-flash-free",
                        "status": "failed",
                        "completed_at": stamp(HOUR),
                    }
                ],
                sessions=[
                    {
                        "thread_id": "thread-1",
                        "last_error": "Upstream request failed: Endpoint is unavailable.",
                        "updated_at": stamp(HOUR),
                    }
                ],
            )
            samples, snapshot = harness.collect()

            self.assertIsNone(
                sample_of(
                    samples,
                    "ghostship_ai_model_available",
                    provider="opencode-go",
                    model="minimax-m3.1-flash-free",
                    reason="model_retired",
                )
            )
            self.assertNotIn(
                "retired",
                harness.state().get("opencode-go/minimax-m3.1-flash-free", {}),
            )


if __name__ == "__main__":
    unittest.main()
