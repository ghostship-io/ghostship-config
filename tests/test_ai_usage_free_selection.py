"""The free providers: the model each one selected, and the models it holds free.

The Providers page lists every free provider: the model the provider
selected for the free tier, and the free models it holds apart from its
paid allowance. OpenCode Go is the case that needs both: the monthly
allowance of the account is spent, and the free route of the provider still
works.

The collector publishes both by projecting the routing snapshot, and it
recomputes nothing. The selection is the provider's first entry in
`tier_winners.free`, in the order of the list. The free models are the
candidates whose `access.billing` is `free` or `promotion`, split by
`available`. The billing class decides, and the access kind never does.

The records in this file are a copy of the live set of 2026-10-23. They
hold invented values only.
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

from metrics import ExactLabel  # noqa: E402
import value_policy  # noqa: E402


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


try:
    free_selection = load("ai_usage_free_selection_module", "free_selection.py")
except FileNotFoundError:
    # The collector does not publish the free selection yet. Every test
    # below says so, and says which reading is missing.
    free_selection = None

main = load("ai_usage_free_selection_main", "main.py")

NOW = 1_800_000_000.0
# The reset of the free window of Google, as the snapshot publishes it.
GOOGLE_RESET = "2026-10-24T00:00:00Z"
GOOGLE_RESET_EPOCH = datetime(
    2026, 10, 24, 0, 0, 0, tzinfo=timezone.utc
).timestamp()

# The eleven providers of the live free tier, in the order of the tier.
FREE_TIER = [
    ("nvidia", "nemotron-free"),
    ("grok", "grok-free-model"),
    ("opencode-go", "beam-free"),
    ("kilo", "kilo-free-model"),
    ("kilo-keyed", "kilo-keyed-free-model"),
    ("openrouter", "openrouter-free-model"),
    ("upstage", "upstage-free-model"),
    ("google", "gemini-3.5-flash-lite"),
    ("inception", "inception-free-model"),
    ("cloudflare-workers-ai", "workers-ai-free-model"),
    ("ovh", "ovh-free-model"),
]


def capacity(
    basis="reported",
    remaining=None,
    pace=None,
    reset_at=None,
    state=None,
):
    """The capacity of a candidate, in the shape the snapshot publishes it."""
    return {
        "remaining_ratio": remaining,
        "pace_delta": pace,
        "capacity_binding": {"reset_at": reset_at},
        "capacity_basis": basis,
        "inference": {"state": state},
    }


def candidate(provider, model, billing, available, cap=None, kind=None):
    """One candidate row of the routing snapshot."""
    if kind is None:
        kind = {
            "free": "dedicated_free",
            "promotion": "provider_promo",
        }.get(billing, "provider_paid")
    return {
        "provider": provider,
        "model": model,
        "available": available,
        "access": {"kind": kind, "billing": billing},
        "capacity": cap if cap is not None else {},
    }


def free_candidate(provider, model, available, cap=None):
    """One free route of a provider."""
    return candidate(provider, model, "free", available, cap)


def account_record(quota_id, kind, remaining=None, reset_at=None, state=None):
    """One window of an account, in the shape the snapshot publishes it."""
    record = {
        "quota_id": quota_id,
        "kind": kind,
        "evidence": "inferred" if kind == "inferred" else "provider_reported",
        "used_ratio": None if remaining is None else round(1.0 - remaining, 4),
        "remaining_ratio": remaining,
        "reset_at": reset_at,
        "seconds_to_reset": None,
        "duration_seconds": None,
        "basis": "",
        "label": "",
        "ends_at": None,
        "check_at": None,
        "provenance": "collector",
    }
    if kind == "inferred":
        record["inference"] = {
            "window": quota_id.split(":", 1)[-1],
            "budget": None,
            "unit": None,
            "scope": None,
            "weights": {},
            "weights_basis": "",
            "episodes": 0,
            "state": state,
        }
    return record


def live_candidates():
    """The candidate rows of the live snapshot, as the collector wrote them."""
    rows = []
    # NVIDIA: the route never saw a limit failure, so the account is
    # learning its window and the share it has is still published.
    rows.append(
        free_candidate(
            "nvidia",
            "nemotron-free",
            True,
            capacity(basis="inferred", remaining=0.6, pace=0.05, state="no_failure"),
        )
    )
    # Groq and the rest of the tier, a free route each.
    for provider, model in FREE_TIER:
        if provider in ("nvidia", "opencode-go", "google", "upstage"):
            continue
        rows.append(
            free_candidate(
                provider,
                model,
                True,
                capacity(basis="reported", remaining=0.8, reset_at=GOOGLE_RESET),
            )
        )
    # OpenCode Go: five free routes, two of them usable, and the
    # subscription routes of the same account, which are not free.
    rows.append(
        free_candidate(
            "opencode-go",
            "beam-free",
            True,
            capacity(basis="published", remaining=1.0, reset_at=GOOGLE_RESET),
        )
    )
    for model, available in (
        ("beam-lite-free", True),
        ("beam-pro-free", False),
        ("beam-mini-free", False),
        ("beam-max-free", False),
    ):
        rows.append(free_candidate("opencode-go", model, available))
    for index in range(1, 27):
        rows.append(candidate("opencode-go", f"subscription-{index:02d}", "subscription", False))
    # Upstage: a paid provider whose route costs nothing right now.
    rows.append(
        candidate(
            "upstage",
            "upstage-free-model",
            "promotion",
            True,
            capacity(basis="reported", remaining=0.5),
        )
    )
    # Google: the free route of the provider, with an inferred window.
    rows.append(
        free_candidate(
            "google",
            "gemini-3.5-flash-lite",
            True,
            capacity(
                basis="inferred",
                remaining=0.9712,
                pace=0.0123,
                reset_at=GOOGLE_RESET,
                state="in_window",
            ),
        )
    )
    # A provider whose winning route ran out of its window: the inference
    # behind it is exhausted, and no share is left.
    rows.append(
        free_candidate(
            "worn",
            "worn-free-model",
            False,
            capacity(basis="inferred", remaining=0.0, state="exhausted"),
        )
    )
    # A provider with two free winners. The first entry of the tier is the
    # selection of the provider.
    rows.append(free_candidate("twinned", "twinned-first", True))
    rows.append(free_candidate("twinned", "twinned-second", True))
    # A provider whose route is dedicated free but whose billing class is
    # unknown: the class decides, so this one is not a free model.
    rows.append(free_candidate("kindly", "kindly-free-model", True))
    rows.append(
        candidate(
            "kindly",
            "kindly-unknown-model",
            "unknown",
            True,
            kind="dedicated_free",
        )
    )
    # Requesty: seven free routes, none of them usable right now.
    for index in range(1, 8):
        rows.append(free_candidate("requesty", f"requesty-free-{index:02d}", False))
    # A paid provider whose account is spent: a free route that is not
    # usable, and an account whose only window was inferred.
    rows.append(free_candidate("walled", "walled-free-model", False))
    # The paid accounts of the host, which are not free providers.
    rows.append(candidate("ollama", "minimax-m3.1-flash", "subscription", True))
    rows.append(candidate("claude", "claude-opus-5-5", "subscription", True))
    return rows


def live_winners():
    """The winners of the live free tier, in the order of the tier."""
    winners = [{"provider": provider, "model": model} for provider, model in FREE_TIER]
    winners.append({"provider": "worn", "model": "worn-free-model"})
    winners.append({"provider": "twinned", "model": "twinned-first"})
    winners.append({"provider": "twinned", "model": "twinned-second"})
    return winners


SNAPSHOT = {
    "candidates": live_candidates(),
    "tier_winners": {"free": live_winners()},
    "quota": {
        "accounts": {
            # OpenCode: an account that only learned a window, and no
            # candidate at all.
            "opencode": [
                account_record("inferred:1m", "inferred", remaining=1.0, state="no_failure")
            ],
            # Ollama and Claude publish a window of their own.
            "ollama": [account_record("monthly", "monthly", remaining=0.9)],
            "claude": [account_record("five_hour", "session", remaining=0.7)],
            # Requesty publishes a window of its own, and holds free routes
            # besides.
            "requesty": [account_record("quota", "quota", remaining=0.4)],
            # The spent account: its only window was inferred.
            "walled": [
                account_record("inferred:exhausted", "inferred", remaining=0.0, state="exhausted")
            ],
        }
    },
}

DISPLAY_NAMES = {
    ("opencode-go", "beam-free"): "Beam Free",
    ("google", "gemini-3.5-flash-lite"): "Gemini 3.5 Flash Lite",
    ("nvidia", "nemotron-free"): "Nemotron Free",
}

# The names the collector publishes for the models of the free tier, in the
# shape it publishes them: the model label holds the id the exposition
# format allows, so a raw id that carries a "/" or an "@" is published
# under its own form. The names are invented, and the ids are the public
# ones of the providers.
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
    (
        "ghostship_ai_model_info",
        {
            "provider": "openrouter",
            "model": "thinkingmachines_inkling-small:free",
            "name": ExactLabel("Inkling Small (free)"),
        },
        1.0,
    ),
    (
        "ghostship_ai_model_info",
        {
            "provider": "cloudflare-workers-ai",
            "model": "_cf_openai_gpt-oss-120b",
            "name": ExactLabel("GPT-OSS 120B"),
        },
        1.0,
    ),
]

# The free tier of the names: the model each provider selected, with the
# raw id the provider gave. NVIDIA holds the same id as Groq and publishes
# no name of its own, and Kilo holds a model that is published nowhere.
NAME_SNAPSHOT = {
    "candidates": [
        free_candidate("groq", "qwen/qwen3.8-27b", True, capacity(basis="reported", remaining=0.8)),
        free_candidate(
            "openrouter",
            "thinkingmachines/inkling-small:free",
            True,
            capacity(basis="reported", remaining=0.4),
        ),
        free_candidate(
            "cloudflare-workers-ai",
            "@cf/openai/gpt-oss-120b",
            True,
            capacity(basis="reported", remaining=0.9),
        ),
        free_candidate(
            "nvidia",
            "qwen/qwen3.8-27b",
            True,
            capacity(basis="reported", remaining=0.7),
        ),
        free_candidate(
            "kilo",
            "nvidia/nemotron-3.5-super-vl:free",
            True,
            capacity(basis="reported", remaining=0.6),
        ),
    ],
    "tier_winners": {
        "free": [
            {"provider": "groq", "model": "qwen/qwen3.8-27b"},
            {"provider": "openrouter", "model": "thinkingmachines/inkling-small:free"},
            {"provider": "cloudflare-workers-ai", "model": "@cf/openai/gpt-oss-120b"},
            {"provider": "nvidia", "model": "qwen/qwen3.8-27b"},
            {"provider": "kilo", "model": "nvidia/nemotron-3.5-super-vl:free"},
        ]
    },
    "quota": {"accounts": {}},
}


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


def selection_rows(samples):
    """The selection of every free provider, by provider."""
    return {
        labels["provider"]: labels
        for name, labels, _value in samples
        if name == "ghostship_ai_free_provider_selection_info"
    }


def free_model_counts(samples):
    """The free models of every provider, by provider and state."""
    return {
        (labels["provider"], labels["state"]): value
        for name, labels, value in samples
        if name == "ghostship_ai_provider_free_models"
    }


def value_of(samples, name, provider):
    """The value of the one series of a provider, or None."""
    for sample_name, labels, value in samples:
        if sample_name == name and labels.get("provider") == provider:
            return value
    return None


def providers_of(samples):
    """Every provider the samples name."""
    return {labels.get("provider") for _name, labels, _value in samples}


class FreeSelectionTests(unittest.TestCase):
    def samples(self, snapshot=None, names=None):
        """The published samples of the free selection."""
        self.assertIsNotNone(
            free_selection,
            "the collector does not publish the free selection yet",
        )
        return free_selection.samples(
            SNAPSHOT if snapshot is None else snapshot,
            DISPLAY_NAMES if names is None else names,
        )

    def test_the_open_code_go_selection_is_its_free_route(self):
        """The monthly allowance is spent, and Beam Free still works."""
        rows = selection_rows(self.samples())
        self.assertEqual(rows["opencode-go"]["model"], "beam-free")
        self.assertEqual(rows["opencode-go"]["basis"], "published")
        self.assertEqual(rows["opencode-go"]["display_name"], "Beam Free")

    def test_the_free_models_of_a_provider_are_split_by_availability(self):
        counts = free_model_counts(self.samples())
        self.assertEqual(counts[("opencode-go", "available")], 2.0)
        self.assertEqual(counts[("opencode-go", "unavailable")], 3.0)

    def test_the_subscription_routes_of_a_paid_provider_are_not_free_models(self):
        """The 26 subscription routes of OpenCode Go are not free models."""
        counts = free_model_counts(self.samples())
        self.assertEqual(counts[("opencode-go", "available")], 2.0)
        self.assertEqual(counts[("opencode-go", "unavailable")], 3.0)

    def test_a_promotional_route_is_a_free_model(self):
        """A paid provider's route that costs nothing right now is free."""
        counts = free_model_counts(self.samples())
        self.assertEqual(counts[("upstage", "available")], 1.0)
        self.assertEqual(counts[("upstage", "unavailable")], 0.0)

    def test_the_billing_class_decides_and_not_the_access_kind(self):
        """A dedicated free route of an unknown class is not a free model."""
        counts = free_model_counts(self.samples())
        self.assertEqual(counts[("kindly", "available")], 1.0)
        self.assertEqual(counts[("kindly", "unavailable")], 0.0)

    def test_the_google_selection_carries_its_inferred_capacity(self):
        samples = self.samples()
        rows = selection_rows(samples)
        self.assertEqual(rows["google"]["model"], "gemini-3.5-flash-lite")
        self.assertEqual(rows["google"]["basis"], "inferred")
        self.assertAlmostEqual(
            value_of(samples, "ghostship_ai_free_provider_selection_remaining_ratio", "google"),
            0.9712,
        )
        self.assertAlmostEqual(
            value_of(samples, "ghostship_ai_free_provider_selection_reset_timestamp_seconds", "google"),
            GOOGLE_RESET_EPOCH,
        )

    def test_an_account_that_is_learning_keeps_the_share_it_has(self):
        """NVIDIA never saw a limit failure: the basis is learning."""
        samples = self.samples()
        rows = selection_rows(samples)
        self.assertEqual(rows["nvidia"]["model"], "nemotron-free")
        self.assertEqual(rows["nvidia"]["basis"], "learning")
        self.assertAlmostEqual(
            value_of(samples, "ghostship_ai_free_provider_selection_remaining_ratio", "nvidia"),
            0.6,
        )

    def test_an_exhausted_inference_stays_inferred_with_no_share_left(self):
        samples = self.samples()
        rows = selection_rows(samples)
        self.assertEqual(rows["worn"]["model"], "worn-free-model")
        self.assertEqual(rows["worn"]["basis"], "inferred")
        self.assertAlmostEqual(
            value_of(samples, "ghostship_ai_free_provider_selection_remaining_ratio", "worn"),
            0.0,
        )

    def test_a_provider_without_a_free_winner_has_no_selection(self):
        """Requesty holds seven free routes, and none of them is usable."""
        samples = self.samples()
        rows = selection_rows(samples)
        self.assertEqual(rows["requesty"]["model"], "")
        self.assertEqual(rows["requesty"]["basis"], "none")
        counts = free_model_counts(samples)
        self.assertEqual(counts[("requesty", "available")], 0.0)
        self.assertEqual(counts[("requesty", "unavailable")], 7.0)

    def test_an_inferred_account_without_candidates_has_no_free_models(self):
        """OpenCode only learned a window: it has no candidate at all."""
        samples = self.samples()
        rows = selection_rows(samples)
        self.assertEqual(rows["opencode"]["model"], "")
        self.assertEqual(rows["opencode"]["basis"], "none")
        counts = free_model_counts(samples)
        self.assertNotIn(("opencode", "available"), counts)
        self.assertNotIn(("opencode", "unavailable"), counts)

    def test_a_spent_inferred_account_without_a_free_candidate_has_no_selection(self):
        samples = self.samples()
        rows = selection_rows(samples)
        self.assertEqual(rows["walled"]["model"], "")
        self.assertEqual(rows["walled"]["basis"], "none")

    def test_a_paid_provider_has_no_series_at_all(self):
        """Ollama and Claude are not free providers."""
        samples = self.samples()
        named = providers_of(samples)
        self.assertNotIn("ollama", named)
        self.assertNotIn("claude", named)

    def test_the_first_free_winner_of_a_provider_is_the_selection(self):
        rows = selection_rows(self.samples())
        self.assertEqual(rows["twinned"]["model"], "twinned-first")

    def test_a_model_without_a_display_name_falls_back_to_its_id(self):
        samples = self.samples(names={})
        rows = selection_rows(samples)
        self.assertEqual(rows["opencode-go"]["display_name"], "beam-free")

    def test_a_selection_without_a_capacity_publishes_no_share(self):
        """An unknown capacity is never published as a zero."""
        snapshot = {
            "candidates": [free_candidate("bare", "bare-free-model", True)],
            "tier_winners": {"free": [{"provider": "bare", "model": "bare-free-model"}]},
            "quota": {"accounts": {}},
        }
        samples = self.samples(snapshot=snapshot)
        self.assertEqual(selection_rows(samples)["bare"]["basis"], "none")
        self.assertIsNone(
            value_of(samples, "ghostship_ai_free_provider_selection_remaining_ratio", "bare")
        )
        self.assertIsNone(
            value_of(samples, "ghostship_ai_free_provider_selection_paced_availability", "bare")
        )
        self.assertIsNone(
            value_of(samples, "ghostship_ai_free_provider_selection_reset_timestamp_seconds", "bare")
        )


class FreeSelectionDisplayNameTests(unittest.TestCase):
    """The name of the model a free provider selected.

    The name is published with the model id the exposition format allows,
    and the id a provider gave is not always one of them. The row of a
    free provider carries the raw id, and it carries the name the
    collector published for that model.
    """

    def samples(self, snapshot=None, names=None):
        """The published samples, with the names the collector published."""
        self.assertIsNotNone(
            free_selection,
            "the collector does not publish the free selection yet",
        )
        return free_selection.samples(
            NAME_SNAPSHOT if snapshot is None else snapshot,
            published_names(PUBLISHED_NAMES) if names is None else names,
        )

    def test_a_model_id_with_a_slash_carries_its_published_name(self):
        """Groq's model is published under an id without its slash."""
        rows = selection_rows(self.samples())
        self.assertEqual(rows["groq"]["display_name"], "Qwen3.8 27B")

    def test_a_free_model_of_another_tier_carries_its_published_name(self):
        """OpenRouter's free model keeps its own name."""
        rows = selection_rows(self.samples())
        self.assertEqual(rows["openrouter"]["display_name"], "Inkling Small (free)")

    def test_a_model_id_with_an_at_sign_carries_its_published_name(self):
        """The Workers AI id starts with an "@"."""
        rows = selection_rows(self.samples())
        self.assertEqual(rows["cloudflare-workers-ai"]["display_name"], "GPT-OSS 120B")

    def test_a_model_without_a_published_name_falls_back_to_its_raw_id(self):
        """Kilo's model is published nowhere, and the row says the id."""
        rows = selection_rows(self.samples())
        self.assertEqual(
            rows["kilo"]["display_name"], "nvidia/nemotron-3.5-super-vl:free"
        )

    def test_the_name_of_another_provider_is_never_used(self):
        """NVIDIA holds Groq's model and publishes no name of its own."""
        rows = selection_rows(self.samples())
        self.assertEqual(rows["nvidia"]["display_name"], "qwen/qwen3.8-27b")

    def test_the_other_labels_of_the_row_are_unchanged(self):
        """The name is the only label the fix touches."""
        rows = selection_rows(self.samples())
        self.assertEqual(rows["groq"]["provider"], "groq")
        self.assertEqual(rows["groq"]["model"], "qwen/qwen3.8-27b")
        self.assertEqual(rows["groq"]["basis"], "reported")


class FreeSelectionPaceStateTests(unittest.TestCase):
    """The pace state of a free provider's selection.

    The selection's left is the remaining ratio of the winning route, and
    its expected left is that share minus the Paced Availability of the
    route. The state is the band the value policy reads from the two; this
    module never draws a band of its own. One series is published per free
    provider.
    """

    def state_samples(self, provider, capacity, winner=True):
        snapshot = {
            "candidates": [free_candidate(provider, "model", True, capacity)],
            "tier_winners": (
                {"free": [{"provider": provider, "model": "model"}]}
                if winner
                else {"free": []}
            ),
            "quota": {"accounts": {}},
        }
        self.assertIsNotNone(
            free_selection,
            "the collector does not publish the free selection yet",
        )
        samples = free_selection.samples(snapshot, {})
        return [
            (labels, value)
            for name, labels, value in samples
            if name == "ghostship_ai_free_provider_selection_pace_state"
        ]

    def state_of(self, provider, capacity):
        states = self.state_samples(provider, capacity)
        self.assertEqual(
            len(states), 1, "a provider publishes exactly one pace state"
        )
        labels, value = states[0]
        self.assertEqual(labels["provider"], provider)
        self.assertEqual(value, 1.0)
        return labels["state"]

    def test_the_google_selection_ahead_of_its_line_is_ahead(self):
        self.assertEqual(
            self.state_of(
                "google", {"remaining_ratio": 0.9712, "pace_delta": 0.3306}
            ),
            "ahead",
        )

    def test_a_selection_with_nothing_left_is_spent(self):
        self.assertEqual(
            self.state_of("worn", {"remaining_ratio": 0.0, "pace_delta": 0.0123}),
            "spent",
        )

    def test_a_selection_with_no_paced_availability_is_unknown(self):
        self.assertEqual(self.state_of("bare", {"remaining_ratio": 0.5}), "unknown")

    def test_a_selection_with_no_capacity_is_unknown(self):
        self.assertEqual(self.state_of("bare", {}), "unknown")

    def test_a_provider_with_no_winner_is_unknown(self):
        states = self.state_samples("bare", {}, winner=False)
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0][0]["state"], "unknown")

    def test_every_provider_has_exactly_one_state_series(self):
        self.assertIsNotNone(
            free_selection,
            "the collector does not publish the free selection yet",
        )
        samples = free_selection.samples(SNAPSHOT, DISPLAY_NAMES)
        rows = selection_rows(samples)
        states = [
            labels
            for name, labels, _value in samples
            if name == "ghostship_ai_free_provider_selection_pace_state"
        ]
        self.assertEqual(
            sorted(labels["provider"] for labels in states), sorted(rows)
        )
        by_provider_state = {
            labels["provider"]: labels["state"] for labels in states
        }
        self.assertEqual(by_provider_state["google"], "on_pace")
        self.assertEqual(by_provider_state["requesty"], "unknown")

    def test_the_band_is_the_value_policy_s(self):
        """The module delegates the band; it does not re-implement it."""
        calls = []

        def recorded(left, expected):
            calls.append((left, expected))
            return "far_behind"

        self.assertIsNotNone(
            free_selection,
            "the collector does not publish the free selection yet",
        )
        with mock.patch.object(value_policy, "pace_state", recorded):
            state = self.state_of(
                "google", {"remaining_ratio": 0.3, "pace_delta": -0.1}
            )
        self.assertEqual(state, "far_behind")
        self.assertEqual(len(calls), 1)
        self.assertAlmostEqual(calls[0][0], 0.3)
        self.assertAlmostEqual(calls[0][1], 0.4)


class FreeSelectionWiringTests(unittest.TestCase):
    def test_the_collector_renders_the_free_selection(self):
        from metrics import SourceResult

        result = SourceResult(
            source="t3",
            status="ok",
            metrics=[
                (
                    "ghostship_ai_model_info",
                    {"provider": "opencode-go", "model": "beam-free", "name": "Beam Free"},
                    1.0,
                )
            ],
        )
        text = main.render([result], [], NOW, 0.0, SNAPSHOT)
        self.assertIn(
            'ghostship_ai_free_provider_selection_info{basis="published",display_name="Beam Free",model="beam-free",provider="opencode-go"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_provider_free_models{provider="opencode-go",state="available"} 2',
            text,
        )
        self.assertIn(
            'ghostship_ai_free_provider_selection_remaining_ratio{provider="google"} 0.9712',
            text,
        )

    def test_the_collector_renders_the_published_name_of_a_free_model(self):
        """The name is read from the series the collector publishes."""
        from metrics import SourceResult

        result = SourceResult(
            source="t3",
            status="ok",
            metrics=list(PUBLISHED_NAMES),
        )
        text = main.render([result], [], NOW, 0.0, NAME_SNAPSHOT)
        self.assertIn(
            'ghostship_ai_free_provider_selection_info{basis="reported",display_name="Qwen3.8 27B",model="qwen_qwen3.8-27b",provider="groq"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_free_provider_selection_info{basis="reported",display_name="Inkling Small (free)",model="thinkingmachines_inkling-small:free",provider="openrouter"} 1',
            text,
        )
        self.assertIn(
            'ghostship_ai_free_provider_selection_info{basis="reported",display_name="GPT-OSS 120B",model="_cf_openai_gpt-oss-120b",provider="cloudflare-workers-ai"} 1',
            text,
        )

    def test_the_help_text_names_the_new_series(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        for name in (
            "ghostship_ai_free_provider_selection_info",
            "ghostship_ai_free_provider_selection_remaining_ratio",
            "ghostship_ai_free_provider_selection_paced_availability",
            "ghostship_ai_free_provider_selection_pace_state",
            "ghostship_ai_free_provider_selection_reset_timestamp_seconds",
            "ghostship_ai_provider_free_models",
        ):
            self.assertIn(f"# HELP {name} ", text)

    def test_the_collector_renders_one_pace_state_per_provider(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        states = [
            line
            for line in text.splitlines()
            if line.startswith("ghostship_ai_free_provider_selection_pace_state{")
        ]
        providers = selection_rows(
            free_selection.samples(SNAPSHOT, DISPLAY_NAMES)
        )
        self.assertEqual(len(states), len(providers))
        self.assertIn(
            'ghostship_ai_free_provider_selection_pace_state{provider="google",state="on_pace"} 1',
            text,
        )

    def test_the_rendering_holds_no_repeated_series(self):
        text = main.render([], [], NOW, 0.0, SNAPSHOT)
        self.assertIn("ghostship_ai_free_provider_selection_info{", text)
        seen = set()
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, labels = line.partition("{")
            key = (name.strip(), labels.partition("}")[0])
            self.assertNotIn(key, seen, f"the file holds {key} twice")
            seen.add(key)


if __name__ == "__main__":
    unittest.main()
