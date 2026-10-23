"""The probe of a candidate route in the routing snapshot.

Every candidate row of the routing snapshot says whether the route answered
its last live probe: the free pool's own probe of the route, or the latest
request the OpenCode record shows for it. A reader no longer guesses: a route
the pool verified says `works`, a route whose probe failed says which class
of failure it was, and a route nothing probed says `unprobed`.

The pool's `status` reply carries `provider_states[provider].probe` with the
state, the category, the model and the moment of the check. The paged `models`
reply carries the pool's own `unavailable_reason` for a parked candidate, so
a parked row names the pool's reason instead of guessing one.

The tests drive the real pool emitters, the real ranking inputs, the real
ranking and the real snapshot builder. A helper-only test would pass while
`routing.json` is wrong.
"""

import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "modules/self-hosted/ai-usage" / "collector"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


metrics = load("probe_metrics", "metrics.py")
main = load("probe_main", "main.py")
catalog_module = load("probe_catalog", "catalog.py")
ranking = load("probe_ranking", "ranking.py")

NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 86400.0
MAX_AGE = 172800

POLICY = {
    "frontierPrimeModels": (),
    "allowedGptModels": (),
    "backgroundProviderInstances": (),
}

# The routes the cases use. The names are invented or the public ids of the
# routes the pool serves; nothing here reads a live provider.
POOL_PROVIDER = "example-pool"
PROBED_MODEL = "example-org/probed-model:free"
UNPROBED_MODEL = "example-org/unprobed-model:free"
OTHER_MODEL = "example-org/other-model:free"
PARKED_MODEL = "example-org/parked-model:free"

# The two routes the live probe field was asked about.
QWEN = ("groq", "qwen/qwen3.8-27b")
OPENROUTER = ("openrouter", "x:free")


def iso(epoch):
    """The UTC moment of an epoch, as the snapshot publishes it."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def window(provider, used_ratio=0.2):
    """The measured window of one account, at the given used share."""
    return {
        "provider": provider,
        "account": "default",
        "model": "*",
        "kind": "monthly",
        "quotaId": "monthly",
        "usedRatio": used_ratio,
        "resetEpoch": NOW + 10 * DAY,
        "durationSeconds": 30 * DAY,
        "source": "t3",
        "observedAtEpoch": NOW,
    }


def event(provider, model, at, outcome, retired=False):
    """One OpenCode request event, shaped the way the reader returns it."""
    return {
        "provider": provider,
        "model": model,
        "at": at,
        "outcome": outcome,
        "usage": 0,
        "window_hint": None,
        "retired": retired,
    }


def route(provider, model, *, available=True, cooldown=None, unavailable_reason=None):
    """One candidate of the pool's paged model catalog."""
    candidate = {"model": model, "available": available}
    if cooldown is not None:
        candidate["cooldown_until"] = cooldown
    if unavailable_reason is not None:
        candidate["unavailable_reason"] = unavailable_reason
    return (provider, model, candidate)


def probe(provider, model, state, category, at):
    """One provider state with the pool's own probe of a route."""
    return (provider, model, state, category, at)


class SnapshotFixture:
    """The real pipeline of one reading: pool reply, inputs, ranking, snapshot."""

    def build(self, *, routes=(), probes=(), measured=(), t3_events=None):
        status = {"provider_states": {}}
        for provider, model, state, category, at in probes:
            status["provider_states"][provider] = {
                "state": "ready",
                "probe": {
                    "state": state,
                    "category": category,
                    "model": model,
                    "at": at,
                },
            }
        catalog_document = {"providers": {}}
        for provider, model, candidate in routes:
            entry = catalog_document["providers"].setdefault(
                provider, {"candidates": []}
            )
            entry["candidates"].append(dict(candidate))
        samples = []
        pool_module = main.pool_module
        pool_module._emit_status(samples, status)
        pool_module._emit_catalog(samples, catalog_document)
        results = [
            metrics.SourceResult(
                source="free_pool",
                status="ok",
                reason="ok",
                metrics=samples,
                observed_at=NOW,
            )
        ]
        context = {}
        if t3_events is not None:
            context["t3_probes"] = main.usage_inference.probes_from_events(t3_events)
        catalog = catalog_module.Catalog({})
        inputs = main.ranking_inputs(results, catalog, context, list(measured), now=NOW)
        context["pool_evidence"] = inputs["pool_evidence"]
        ranked = ranking.rank_models(
            models=[
                ranking.ModelRecord(provider, model)
                for provider, model in inputs["inventory"]
            ],
            catalog=catalog,
            quota_windows=inputs["windows"],
            free_models=inputs["free"],
            promo_models=inputs["promo"],
            external_availability=inputs["external"],
            usage_tokens=inputs["usage"],
            now=NOW,
        )
        return main.build_snapshot(
            results,
            ranked,
            context,
            NOW,
            measured_windows=list(measured),
            catalog=catalog,
            free_models=inputs["free"],
            promo_models=inputs["promo"],
        )

    def row(self, data, provider, model):
        for row in data["candidates"]:
            if (row["provider"], row["model"]) == (provider, model):
                return row
        raise AssertionError(f"the snapshot has no row for {provider}/{model}")


class PoolProbeTests(unittest.TestCase, SnapshotFixture):
    """The free pool's own probe of a route, as the row publishes it."""

    def test_a_verified_pool_probe_of_the_route_works(self):
        checked = NOW - HOUR
        data = self.build(
            routes=[route(QWEN[0], QWEN[1])],
            probes=[probe(QWEN[0], QWEN[1], "verified_ok", "success", checked)],
            measured=[window(QWEN[0])],
        )
        row = self.row(data, *QWEN)
        self.assertEqual(
            row["probe"],
            {
                "state": "works",
                "class": "success",
                "checked_at": iso(checked),
                "source": "pool_probe",
                "max_age_seconds": MAX_AGE,
            },
        )

    def test_every_failed_category_names_its_class(self):
        classes = (
            ("rate_limited", "quota"),
            ("quota_exhausted", "quota"),
            ("free_daily_exhausted", "quota"),
            ("credentials_or_access", "auth"),
            ("model_unavailable", "model_not_found"),
            ("no_verified_free_route", "catalog_mismatch"),
            ("awaiting_approval", "policy_parked"),
            ("timeout", "timeout"),
            ("upstream_error", "upstream_error"),
            ("something_else", "upstream_error"),
        )
        for category, expected in classes:
            with self.subTest(category=category):
                data = self.build(
                    routes=[route(POOL_PROVIDER, PROBED_MODEL)],
                    probes=[
                        probe(
                            POOL_PROVIDER,
                            PROBED_MODEL,
                            "failed",
                            category,
                            NOW - HOUR,
                        )
                    ],
                    measured=[window(POOL_PROVIDER)],
                )
                row = self.row(data, POOL_PROVIDER, PROBED_MODEL)
                self.assertEqual(row["probe"]["state"], "fails")
                self.assertEqual(row["probe"]["class"], expected)
                self.assertEqual(row["probe"]["source"], "pool_probe")

    def test_a_probe_that_sent_nothing_is_unprobed(self):
        # The pool marks a route quota_or_cooldown without sending anything:
        # no route answered, so there is no probe to report.
        data = self.build(
            routes=[route(POOL_PROVIDER, PROBED_MODEL)],
            probes=[
                probe(
                    POOL_PROVIDER,
                    PROBED_MODEL,
                    "parked",
                    "quota_or_cooldown",
                    NOW - HOUR,
                )
            ],
            measured=[window(POOL_PROVIDER)],
        )
        row = self.row(data, POOL_PROVIDER, PROBED_MODEL)
        self.assertEqual(row["probe"]["state"], "unprobed")
        self.assertEqual(row["probe"]["class"], "")

    def test_a_probe_of_another_model_leaves_the_row_unprobed(self):
        data = self.build(
            routes=[
                route(POOL_PROVIDER, PROBED_MODEL),
                route(POOL_PROVIDER, OTHER_MODEL),
            ],
            probes=[
                probe(
                    POOL_PROVIDER,
                    OTHER_MODEL,
                    "verified_ok",
                    "success",
                    NOW - HOUR,
                )
            ],
            measured=[window(POOL_PROVIDER)],
        )
        row = self.row(data, POOL_PROVIDER, PROBED_MODEL)
        self.assertEqual(row["probe"]["state"], "unprobed")
        self.assertIsNone(row["probe"]["checked_at"])


class T3ProbeTests(unittest.TestCase, SnapshotFixture):
    """The latest OpenCode request of a route, as the row publishes it."""

    def test_a_successful_request_works(self):
        checked = NOW - HOUR
        data = self.build(
            routes=[route(OPENROUTER[0], OPENROUTER[1])],
            t3_events=[event(OPENROUTER[0], OPENROUTER[1], checked, "success")],
            measured=[window(OPENROUTER[0])],
        )
        row = self.row(data, *OPENROUTER)
        self.assertEqual(
            row["probe"],
            {
                "state": "works",
                "class": "success",
                "checked_at": iso(checked),
                "source": "t3_probe",
                "max_age_seconds": MAX_AGE,
            },
        )

    def test_a_limit_request_fails_as_quota(self):
        data = self.build(
            routes=[route(OPENROUTER[0], OPENROUTER[1])],
            t3_events=[
                event(OPENROUTER[0], OPENROUTER[1], NOW - HOUR, "limit")
            ],
            measured=[window(OPENROUTER[0])],
        )
        row = self.row(data, *OPENROUTER)
        self.assertEqual(row["probe"]["state"], "fails")
        self.assertEqual(row["probe"]["class"], "quota")
        self.assertEqual(row["probe"]["source"], "t3_probe")

    def test_a_retired_request_fails_as_model_not_found(self):
        data = self.build(
            routes=[route(OPENROUTER[0], OPENROUTER[1])],
            t3_events=[
                event(OPENROUTER[0], OPENROUTER[1], NOW - HOUR, "other", True)
            ],
            measured=[window(OPENROUTER[0])],
        )
        row = self.row(data, *OPENROUTER)
        self.assertEqual(row["probe"]["state"], "fails")
        self.assertEqual(row["probe"]["class"], "model_not_found")

    def test_the_latest_request_of_the_route_is_the_probe(self):
        data = self.build(
            routes=[route(OPENROUTER[0], OPENROUTER[1])],
            t3_events=[
                event(OPENROUTER[0], OPENROUTER[1], NOW - 3 * HOUR, "limit"),
                event(OPENROUTER[0], OPENROUTER[1], NOW - HOUR, "success"),
            ],
            measured=[window(OPENROUTER[0])],
        )
        row = self.row(data, *OPENROUTER)
        self.assertEqual(row["probe"]["state"], "works")
        self.assertEqual(row["probe"]["checked_at"], iso(NOW - HOUR))


class NewestReadingTests(unittest.TestCase, SnapshotFixture):
    """When both readings exist, the newer one is the probe."""

    def test_a_newer_opencode_request_wins_over_the_pool_probe(self):
        data = self.build(
            routes=[route(QWEN[0], QWEN[1])],
            probes=[
                probe(QWEN[0], QWEN[1], "verified_ok", "success", NOW - 2 * HOUR)
            ],
            t3_events=[event(QWEN[0], QWEN[1], NOW - HOUR, "limit")],
            measured=[window(QWEN[0])],
        )
        row = self.row(data, *QWEN)
        self.assertEqual(row["probe"]["state"], "fails")
        self.assertEqual(row["probe"]["class"], "quota")
        self.assertEqual(row["probe"]["source"], "t3_probe")

    def test_a_newer_pool_probe_wins_over_the_opencode_request(self):
        data = self.build(
            routes=[route(QWEN[0], QWEN[1])],
            probes=[
                probe(QWEN[0], QWEN[1], "verified_ok", "success", NOW - HOUR)
            ],
            t3_events=[event(QWEN[0], QWEN[1], NOW - 2 * HOUR, "limit")],
            measured=[window(QWEN[0])],
        )
        row = self.row(data, *QWEN)
        self.assertEqual(row["probe"]["state"], "works")
        self.assertEqual(row["probe"]["class"], "success")
        self.assertEqual(row["probe"]["source"], "pool_probe")


class AgeTests(unittest.TestCase, SnapshotFixture):
    """A reading older than two days is not a probe any more."""

    def test_a_reading_172801_seconds_old_is_stale(self):
        checked = NOW - (MAX_AGE + 1)
        data = self.build(
            routes=[route(QWEN[0], QWEN[1])],
            probes=[probe(QWEN[0], QWEN[1], "verified_ok", "success", checked)],
            measured=[window(QWEN[0])],
        )
        row = self.row(data, *QWEN)
        self.assertEqual(row["probe"]["state"], "unprobed")
        self.assertEqual(row["probe"]["class"], "")
        # The old reading is kept: a reader sees when the route was last
        # probed even though the reading no longer counts.
        self.assertEqual(row["probe"]["checked_at"], iso(checked))
        self.assertEqual(row["probe"]["source"], "pool_probe")

    def test_a_reading_exactly_172800_seconds_old_still_counts(self):
        checked = NOW - MAX_AGE
        data = self.build(
            routes=[route(QWEN[0], QWEN[1])],
            probes=[probe(QWEN[0], QWEN[1], "verified_ok", "success", checked)],
            measured=[window(QWEN[0])],
        )
        row = self.row(data, *QWEN)
        self.assertEqual(row["probe"]["state"], "works")
        self.assertEqual(row["probe"]["checked_at"], iso(checked))


class NoReadingTests(unittest.TestCase, SnapshotFixture):
    """A route nothing probed says so, with no guessed moment or source."""

    def test_a_route_with_no_probe_is_unprobed(self):
        data = self.build(
            routes=[route(POOL_PROVIDER, UNPROBED_MODEL)],
            measured=[window(POOL_PROVIDER)],
        )
        row = self.row(data, POOL_PROVIDER, UNPROBED_MODEL)
        self.assertEqual(
            row["probe"],
            {
                "state": "unprobed",
                "class": "",
                "checked_at": None,
                "source": None,
                "max_age_seconds": MAX_AGE,
            },
        )


class ParkedReasonTests(unittest.TestCase, SnapshotFixture):
    """A parked pool route shows the pool's own reason."""

    REASONS = (
        (
            "hosting_restricted",
            "the owner's hosting rule keeps this route to research work",
        ),
        (
            "account_policy",
            "the account's data policy or workloads do not allow development work",
        ),
        ("suspended", "the account is suspended"),
    )

    def test_the_pool_reason_is_named(self):
        for reason, expected in self.REASONS:
            with self.subTest(reason=reason):
                data = self.build(
                    routes=[
                        route(
                            POOL_PROVIDER,
                            PARKED_MODEL,
                            available=False,
                            unavailable_reason=reason,
                        )
                    ],
                    measured=[window(POOL_PROVIDER)],
                )
                row = self.row(data, POOL_PROVIDER, PARKED_MODEL)
                self.assertFalse(row["available"])
                self.assertEqual(row["availability"]["reason"], expected)

    def test_a_cooldown_reason_names_the_moment_it_ends(self):
        cooldown = NOW + HOUR
        data = self.build(
            routes=[
                route(
                    POOL_PROVIDER,
                    PARKED_MODEL,
                    available=False,
                    cooldown=cooldown,
                    unavailable_reason="cooldown",
                )
            ],
            measured=[window(POOL_PROVIDER)],
        )
        row = self.row(data, POOL_PROVIDER, PARKED_MODEL)
        self.assertEqual(
            row["availability"]["reason"],
            f"cooling down in the free pool until {iso(cooldown)}",
        )

    def test_a_candidate_without_a_reason_keeps_the_current_text(self):
        cooldown = NOW + HOUR
        data = self.build(
            routes=[
                route(POOL_PROVIDER, PARKED_MODEL, available=False, cooldown=cooldown)
            ],
            measured=[window(POOL_PROVIDER)],
        )
        row = self.row(data, POOL_PROVIDER, PARKED_MODEL)
        self.assertEqual(
            row["availability"]["reason"],
            f"cooling down in the free pool until {iso(cooldown)}",
        )

    def test_a_candidate_without_a_reason_and_cooldown_keeps_the_current_text(self):
        data = self.build(
            routes=[route(POOL_PROVIDER, PARKED_MODEL, available=False)],
            measured=[window(POOL_PROVIDER)],
        )
        row = self.row(data, POOL_PROVIDER, PARKED_MODEL)
        self.assertEqual(
            row["availability"]["reason"],
            "the free pool does not offer the route for development work",
        )


class ReaderWiringTests(unittest.TestCase):
    """The OpenCode record's probes reach the collector's context."""

    def test_read_and_infer_carries_the_latest_probe_of_each_route(self):
        events = [
            event(OPENROUTER[0], OPENROUTER[1], NOW - 3 * HOUR, "limit"),
            event(OPENROUTER[0], OPENROUTER[1], NOW - HOUR, "success"),
        ]
        reading = {"status": "ok", "reason": "ok", "events": events}
        usage_inference = main.usage_inference
        with mock.patch.object(
            usage_inference.opencode_reader,
            "collect_events",
            return_value=reading,
        ):
            inferred = usage_inference.read_and_infer(
                NOW,
                opencode_db="unused",
                events_cache="unused",
                pool_ledger=None,
                routes={OPENROUTER},
            )
        self.assertEqual(
            inferred.probes[OPENROUTER],
            {
                "state": "works",
                "class": "success",
                "checked_at": NOW - HOUR,
                "source": "t3_probe",
            },
        )


if __name__ == "__main__":
    unittest.main()
