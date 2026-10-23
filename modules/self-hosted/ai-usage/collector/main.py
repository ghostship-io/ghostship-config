"""Collect AI provider usage, limits, and free models into Prometheus metrics.

The collector reads T3 Code's own readings, the provider
APIs T3 Code does not read, the free inference pool, and the public model
catalog, and writes one textfile for node_exporter.

Managed model favorites and the new-thread default use authenticated settings
patches. Nothing here starts, stops or restarts a provider, container or T3.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aa  # noqa: E402
import model_selection  # noqa: E402
import aa_3d  # noqa: E402
import account_availability as account_availability_module  # noqa: E402
import card_order as card_order_module  # noqa: E402
import catalog as catalog_module  # noqa: E402
import codes  # noqa: E402
import free_selection as free_selection_module  # noqa: E402
import outcomes as outcomes_module  # noqa: E402
import pool as pool_module  # noqa: E402
import pool_published  # noqa: E402
import published as published_module  # noqa: E402
import pools  # noqa: E402
import quota as quota_module  # noqa: E402
import providers as providers_module  # noqa: E402
import ranking as ranking_module  # noqa: E402
import reset_overrides  # noqa: E402
import announced_resets  # noqa: E402
import runtime_state as runtime_state_module  # noqa: E402
import snapshot as snapshot_module  # noqa: E402
import static_routes as static_routes_module  # noqa: E402
import t3source  # noqa: E402
import threed as threed_module  # noqa: E402
import usage_inference  # noqa: E402
from metrics import MetricWriter, Sample, SourceResult  # noqa: E402
# The scope of a quota window lives with the other window rules now, in the
# quota module. Both names are imported here, so the collector keeps one
# place that knows the scope of a window.
from quota import WINDOW_SCOPES, _window_scope  # noqa: E402,F401
from t3client import T3Client, T3Error  # noqa: E402
from util import now as wall_clock  # noqa: E402

T3_HOME = "/srv/apps/t3code/home"
T3_SERVER_FILE = "/run/ghostship-integrations/t3-server.json"
T3_SESSION_FILE = "/run/ghostship-integrations/t3-token"
SECRETS_ENV_FILE = "/run/ghostship-secrets/t3code.env"
POOL_SERVER_FILE = "/run/ghostship-integrations/inference-server.json"
POOL_TOKEN_FILE = "/run/ghostship-integrations/inference-token"
POOL_LEDGER_FILE = f"{T3_HOME}/.local/state/ghostship-agent/runtime/jobs.sqlite"
# The OpenCode request records, inside the T3 Code home. The reader opens the
# database read only, and the unit's read only paths cover the home.
OPENCODE_DB_FILE = f"{T3_HOME}/{usage_inference.OPENCODE_DB_RELATIVE}"
# The reader's own cache of the OpenCode events, in the collector's state
# directory. The state directory is writable and nothing else is.
EVENTS_CACHE_FILE = usage_inference.EVENTS_CACHE_PATH
# The T3 Code state, read only. It carries the observed failures of the
# routes: a child that could not start, a provider that reported its
# allowance spent, a model that was refused.
T3_STATE_FILE = f"{T3_HOME}/.t3/userdata/statev2.sqlite"
CATALOG_FILE = f"{T3_HOME}/.cache/opencode/models.json"
# The smallest 3D prior that earns a place in the 3D tier.

# The owner's direction for the agents that run in this environment. It is a
# policy, not a measurement, and it never changes a provider reading.
OWNER_POLICY = {
    "frontierPrimeModels": ("claude-opus-5-5", "gpt-6.1-sol"),
    "allowedGptModels": ("gpt-6.1-sol",),
    "backgroundProviderInstances": ("opencode",),
    # The models the owner excludes from every selection. They stay visible
    # in the usage and the quota readings; they are never a winner and never
    # a recommendation.
    "excludedModels": ("gpt-6-astra", "claude-fable-5", "claude-fable-5-1"),
    # The frontier authority reviews every implementation before it is
    # integrated. A review by a bulk model is never a final approval, and a
    # required frontier that is unavailable is waited for, never replaced.
    "frontierReviewAuthority": {
        "provider_instance_id": "codex",
        "model_id": "gpt-6.1-sol",
    },
    "basis": "owner direction, 2026-10-21",
}

# The routing snapshot a consumer reads. The producer writes it; a consumer
# only reads it. It is separate from the internal ranking state.
SNAPSHOT_PATH = "/var/lib/ghostship-ai-usage/routing.json"

# The cached Artificial Analysis feed. The daily procedure reads the feed and
# writes the cache; the collector only reads the cache, so the free request
# budget belongs to one place.
AA_CACHE_PATH = "/var/lib/ghostship-ai-usage/artificial-analysis.json"

# The AA-3D board, written by the same pull of the public pages. Without
# the board there is no 3D rank: the 3D tier stays empty and the models
# that qualify for it are not reserved.
AA_3D_CACHE_PATH = "/var/lib/ghostship-ai-usage/aa-3d.json"

# The durable facts of the models, written by the daily procedure.
FACTS_PATH = "/var/lib/ghostship-ai-usage/facts.json"

# The model identities: which routes serve one model. The file sits beside
# the runtime policy, and the collector reads it when it is there.
MODEL_IDENTITIES_FILE = "model-identities.json"

# The delegation ledger and its backfill. The ledger is a SQLite database
# with the rounds that were observed, and the backfill carries the rounds
# the ledger does not have. The collector opens the ledger read only and
# never writes it.
DELEGATION_DIR = f"{T3_HOME}/.local/state/ghostship-agent/delegation"
DELEGATION_LEDGER_FILE = f"{DELEGATION_DIR}/ledger.sqlite3"
DELEGATION_BACKFILL_FILE = f"{DELEGATION_DIR}/backfill.json"

# Every account the dashboard covers, and where its readings come from.
# A provider without a reader still gets a row, so nothing disappears.
COVERAGE = (
    ("codex", "t3"),
    ("claude", "t3"),
    ("grok", "grok"),
    ("antigravity", "antigravity"),
    ("opencode-go", "opencode-go"),
    ("openrouter", "openrouter"),
    ("ollama", "ollama"),
    ("opencode", "t3_usage"),
    ("cursor", "t3"),
    ("pi", "t3_usage"),
)

METRIC_HELP = {
    "ghostship_ai_source_success": "Whether the last collection of this source succeeded.",
    "ghostship_ai_source_status": "One for the current status of a source.",
    "ghostship_ai_provider_status": "One for the current state of a provider account.",
    "ghostship_ai_source_last_success_timestamp_seconds": "When a source last produced a reading.",
    "ghostship_ai_source_observed_timestamp_seconds": "When the reported reading was observed.",
    "ghostship_ai_source_duration_seconds": "How long a source took to read.",
    "ghostship_ai_quota_used_ratio": "Used share of a subscription or quota window.",
    "ghostship_ai_quota_reset_timestamp_seconds": "When a quota window resets.",
    "ghostship_ai_quota_observed_timestamp_seconds": "When a quota reading was observed.",
    "ghostship_ai_quota_state": "One for the state a provider reports for a window.",
    "ghostship_ai_quota_entitlement": (
        "One for every reading of a quota entitlement; a verified alias of "
        "the same window shares the entitlement id and keeps its own source."
    ),
    "ghostship_ai_entitlement_info": (
        "One for one canonical display reading per entitlement, even when no "
        "numeric reading is usable. The labels carry the basis of the "
        "numbers and the end of the entitlement, which is empty when the "
        "provider publishes none."
    ),
    "ghostship_ai_entitlement_used_ratio": (
        "The used share of the canonical reading of an entitlement."
    ),
    "ghostship_ai_entitlement_reset_timestamp_seconds": (
        "When the canonical reading of an entitlement resets."
    ),
    "ghostship_ai_entitlement_expected_used_ratio": (
        "The even-spend line of the canonical reading of an entitlement."
    ),
    "ghostship_ai_entitlement_pace_delta_ratio": (
        "The canonical reading's expected minus measured share."
    ),
    "ghostship_ai_entitlement_observed_timestamp_seconds": (
        "When the canonical reading of an entitlement was observed."
    ),
    "ghostship_ai_account_amount": "Reported balance, usage, cap, or request count.",
    "ghostship_ai_account_flag": "One for a reported account flag.",
    "ghostship_ai_account_observed_timestamp_seconds": "When an account reading was observed.",
    "ghostship_ai_usage_tokens": "Tokens used, by kind and window.",
    "ghostship_ai_usage_cost_usd": "Cost in US dollars, by basis and window.",
    "ghostship_ai_usage_unpriced_records": "Records that no price could be found for.",
    "ghostship_ai_usage_observed_timestamp_seconds": "When usage was observed.",
    "ghostship_ai_free_model": "One for a model that can be used at no cost.",
    "ghostship_ai_free_model_available": "Whether a free model can be selected now.",
    "ghostship_ai_free_model_price_usd_per_mtok": "The catalog price of a free model.",
    "ghostship_ai_free_model_observed_timestamp_seconds": "When the free model list was read.",
    "ghostship_ai_pool_model_info": "One for a model the free pool may use.",
    "ghostship_ai_pool_model_available": "Whether a pool model is available now.",
    "ghostship_ai_pool_model_unavailable_reason": (
        "The pool's own reason a model is unavailable, with the account's or "
        "the owner's rule it names."
    ),
    "ghostship_ai_pool_probe": (
        "One for the free pool's own probe of a route, with the state and "
        "category of the answer, the provider and the model it checked."
    ),
    "ghostship_ai_pool_probe_timestamp_seconds": (
        "When the free pool checked a route."
    ),
    "ghostship_ai_pool_model_selected": "Whether a pool model is the selected one.",
    "ghostship_ai_pool_model_cooldown_until_seconds": "When a pool model's cooldown ends.",
    "ghostship_ai_pool_route_last_used_timestamp_seconds": (
        "When the free pool last sent a job to a route. The least recently "
        "used route breaks the tie inside the quality band of the free tier."
    ),
    "ghostship_ai_pool_model_admission": "Whether a pool model is admitted for a workload.",
    "ghostship_ai_pool_limit": "A local admission limit of the free pool.",
    "ghostship_ai_pool_observed_limit": (
        "A limit the provider's own response headers carried, as observed."
    ),
    "ghostship_ai_pool_published_limit": (
        "A limit the provider itself publishes, with the source it was read "
        "from."
    ),
    "ghostship_ai_provider_limit": (
        "A limit of a free provider, with the basis it was read with: "
        "published, configured, observed or unknown."
    ),
    "ghostship_ai_pool_cooldown_invalid": (
        "One for a cooldown of a pool route that cannot be true; the route is "
        "not blocked by it."
    ),
    "ghostship_ai_pool_admission": (
        "Whether a pool route is admitted for a workload, with the score the "
        "pool's own bench gave it."
    ),
    "ghostship_ai_pool_provider_state": "One for the current state of a pool provider.",
    "ghostship_ai_pool_health_events": "Successes and failures recorded for a pool model.",
    "ghostship_ai_pool_latency_seconds": "Observed latency of a pool model.",
    "ghostship_ai_pool_concurrency": "Current and allowed concurrency of a pool provider.",
    "ghostship_ai_pool_recent_jobs": (
        "The count of recent jobs in the free pool with these labels."
    ),
    "ghostship_ai_pool_quota_amount": "A quota amount observed in provider response headers.",
    "ghostship_ai_pool_quota_reset_seconds": "When an observed quota resets.",
    "ghostship_ai_pool_quota_observed_timestamp_seconds": "When an observed quota was seen.",
    "ghostship_ai_pool_ledger_requests": "Requests the free pool reserved over a window.",
    "ghostship_ai_pool_catalog_updated_timestamp_seconds": "When the pool catalog was refreshed.",
    "ghostship_ai_provider_coverage": "One for every provider the dashboard covers.",
    "ghostship_ai_route_unavailable": (
        "One for a route the T3 Code state says is unavailable, with the "
        "scope of the failure and the reason code."
    ),
    "ghostship_ai_route_unavailable_observed_timestamp_seconds": (
        "When the T3 Code state observed the failure of a route."
    ),
    "ghostship_ai_model_rank": "The rank of a model inside a tier, 1 is best.",
    "ghostship_ai_model_score": "The ranking score of a model inside a tier.",
    "ghostship_ai_model_trust_info": (
        "The trust of a model for a task type, with the level it holds and "
        "the reason it holds it."
    ),
    "ghostship_ai_model_outcome": (
        "The measured outcome of a model for a task type: the prior p0, the "
        "prior strength k, the observed rounds n and s, and the quality p."
    ),
    "ghostship_ai_model_quality": "The quality score of a model.",
    "ghostship_ai_model_quality_score": (
        "The display quality score of a model: one integer 0..100 per model, "
        "comparable across every tier, with the basis it was built from."
    ),
    "ghostship_ai_model_quality_rounds": (
        "The observed rounds behind a model's display quality score, summed "
        "over every task type: n the rounds and s the accepted ones."
    ),
    "ghostship_ai_model_available": (
        "Whether a model can be used right now, with the reason it cannot."
    ),
    "ghostship_ai_model_capacity_remaining": (
        "The remaining share of a model's account capacity, zero when it is spent."
    ),
    "ghostship_ai_model_quota_unknown": (
        "One for a model whose headroom is unknown, with the reason it is unknown."
    ),
    "ghostship_ai_model_capacity_expires_in_seconds": "When the model's account capacity expires.",
    "ghostship_ai_model_capacity_basis": (
        "Where the capacity of a model comes from: a reading the provider "
        "reported, an inference from the limit failures of the route, a "
        "statement the provider publishes, or nothing at all."
    ),
    "ghostship_ai_model_capacity_budget": (
        "The budget an inferred capacity was measured against, in the unit "
        "it was measured in."
    ),
    "ghostship_ai_model_capacity_episodes": (
        "The limit episodes an inferred capacity was measured from."
    ),
    "ghostship_ai_inference_unmatched_events": (
        "The recorded events whose route is not in the collector's "
        "inventory. They are counted and never guessed."
    ),
    "ghostship_ai_model_tier": "One for every tier a model belongs to.",
    "ghostship_ai_model_info": "One for a candidate model, with the human name of the model.",
    "ghostship_ai_model_evaluated_timestamp_seconds": "When a model was last evaluated.",
    "ghostship_ai_three_d_usage_tokens": "Tokens spent on 3D printing work.",
    # The two series below are no longer emitted: the 3D prior and its blended
    # score were a judgement, and the owner removed them. They stay declared
    # so a dashboard that still queries them shows no data, not an error.
    "ghostship_ai_three_d_prior": "Removed: no 3D prior is published.",
    "ghostship_ai_three_d_score": "Removed: no blended 3D score is published.",
    "ghostship_ai_three_d_observed_timestamp_seconds": "When the 3D reading was taken.",
    "ghostship_ai_model_strength": (
        "The verified Artificial Analysis intelligence index of the model; a "
        "model without a record has no strength and is unranked."
    ),
    "ghostship_ai_model_relative_cost": "The blended token price of a model, the provider's own listing.",
    "ghostship_ai_model_value": "The value of a model: the strength over the relative price.",
    "ghostship_ai_model_intelligence_index": "A benchmark index of a model.",
    "ghostship_ai_model_cost_per_task": "What a measured task costs, never a token price.",
    "ghostship_ai_model_throughput": "The median performance of a model.",
    "ghostship_ai_model_token_price": "A token price of a model, the provider's own listing.",
    "ghostship_ai_model_fact": "The state of the durable fact of a model.",
    "ghostship_ai_model_fact_fetched_timestamp_seconds": "When the fact of a model was read.",
    "ghostship_ai_model_fact_confidence": "The confidence a fact carries.",
    "ghostship_ai_model_winner": "One for the winner of a provider and tier.",
    "ghostship_ai_model_winner_position": "The position of the winner among the providers of a tier.",
    "ghostship_ai_policy_frontier_workhorse": (
        "One for every model the owner's policy names a frontier workhorse."
    ),
    "ghostship_ai_policy_excluded_model": (
        "One for every model the owner's policy excludes from selection; it "
        "stays visible in the usage and the quota readings."
    ),
    "ghostship_ai_model_new": (
        "One for a model the Artificial Analysis pull found that the last "
        "pull did not carry. It is the re-ranking trigger."
    ),
    "ghostship_ai_model_changed": (
        "One for a model whose Artificial Analysis measurement changed since "
        "the last pull."
    ),
    "ghostship_ai_feed_status": (
        "The state of the Artificial Analysis pull: the source, the state and "
        "the number of records."
    ),
    "ghostship_ai_model_aa_condition": (
        "The reasoning condition the benchmark measured the model under, and "
        "whether that condition is confirmed."
    ),
    "ghostship_ai_model_execution_reasoning": (
        "The execution reasoning the owner's policy proposes for a model: the "
        "default, the escalation, and whether the model supports them."
    ),
    "ghostship_ai_model_capacity_binding": (
        "The window that binds the capacity of a model, and the share of it "
        "that is left."
    ),
    "ghostship_ai_model_pace_binding": (
        "The window that binds the pace of a model, and the pace itself."
    ),
    "ghostship_ai_frontier_member": (
        "One for a model the owner's policy admits to the frontier, with the "
        "state it is in."
    ),
    "ghostship_ai_frontier_wait_seconds": (
        "The seconds until the frontier model becomes available again."
    ),
    "ghostship_ai_three_d_elo": "The measured AA-3D Elo of a model.",
    "ghostship_ai_model_value_3d": (
        "The value of a model for 3D work: the intelligence, the AA-3D "
        "capability and the cost, with the weights of the policy."
    ),
    "ghostship_ai_model_reserved": (
        "One for a model that is reserved for the 3D tier: it ranks after "
        "every other winner of the tier, and it is not used for the work of "
        "the tier while its provider's capacity is low."
    ),
    "ghostship_ai_calculation_component": "One for each part of the calculation of a winner.",
    "ghostship_ai_calculation_weight": "The weight of a part of the calculation.",
    "ghostship_ai_calculation_transform": (
        "The transform of a calculated input, with the name of the transform in "
        "force."
    ),
    "ghostship_ai_calculation_gate": "One for each gate of the tiers.",
    "ghostship_ai_quota_duration_seconds": "The length of a quota window.",
    "ghostship_ai_quota_expected_used_ratio": (
        "The usage an even spend would have reached by now; the white line."
    ),
    "ghostship_ai_quota_pace_delta_ratio": (
        "The expected usage minus the measured usage; positive is behind budget."
    ),
    "ghostship_ai_model_pace_delta_ratio": (
        "The most constraining pace among the windows of a model."
    ),
    "ghostship_ai_provider_paced_availability": (
        "The Paced Availability of a provider: the share left minus the "
        "expected share left in its most constraining window. Positive means "
        "the provider is ahead of the pace the window draws, and a higher "
        "number ranks first. It is the same number as the pace delta of that "
        "window."
    ),
    "ghostship_ai_model_paced_availability": (
        "The Paced Availability of a model: the share left minus the expected "
        "share left in its most constraining window. Positive means the model "
        "is ahead of the pace the window draws, and a higher number ranks "
        "first. It is the same number as the model's pace delta ratio."
    ),
    "ghostship_ai_provider_capacity_remaining_ratio": (
        "The lowest applicable account window of a provider; a spent window "
        "publishes zero, and an unknown window publishes nothing."
    ),
    "ghostship_ai_provider_capacity_windows": (
        "The account windows of a provider, split into known and unknown."
    ),
    "ghostship_ai_account_window_remaining_ratio": (
        "The share of an account window that is left. One series per window "
        "of an account, and the label says which window it is."
    ),
    "ghostship_ai_account_window_expected_remaining_ratio": (
        "The share of an account window that an even spend would have left "
        "by now; the line of the bar."
    ),
    "ghostship_ai_account_window_pace_state": (
        "The band of an account window against its own even-spend line, in "
        "the state label: ahead, on_pace, behind, far_behind, spent or "
        "unknown. One series per window, with the labels of "
        "ghostship_ai_account_window_remaining_ratio plus the state."
    ),
    "ghostship_ai_account_window_reset_timestamp_seconds": (
        "When an account window resets."
    ),
    "ghostship_ai_account_window_check_timestamp_seconds": (
        "When an account window was checked: the moment the provider "
        "reported it, in seconds. It is the moment of the reading the row "
        "is drawn from, so the age of a card is the age of its reading. A "
        "reading without a check time publishes none."
    ),
    "ghostship_ai_account_window_rolling": (
        "One for an account window that rolls: a window shorter than five "
        "minutes with no reset."
    ),
    "ghostship_ai_account_window_order": (
        "The place a window takes in the card of its account: 1 is the "
        "session window, and a monthly window comes after a weekly one."
    ),
    "ghostship_ai_account_window_pace_delta_points": "Weekly or monthly window pace in percentage points, from its own reading.",
    "ghostship_ai_account_window_missing": "Reported provider limits could not be read; this is not a learned window.",
    "ghostship_ai_account_window_learning": (
        "One for an account that publishes no window of its own yet."
    ),
    "ghostship_ai_account_availability": (
        "Whether an account can serve right now, with the reason it cannot "
        "when it cannot, and the basis of its limit: learning, unpublished or "
        "published."
    ),
    "ghostship_ai_account_availability_check_timestamp_seconds": (
        "When the availability of an account was observed: the newest "
        "observation of the routes that were counted."
    ),
    "ghostship_ai_account_card_order": (
        "The place the card of an account takes on the Providers page: 1 is "
        "the first card, and the places hold no gap. Scope is t3 when any "
        "candidate is mapped to the live T3 catalog, otherwise free."
    ),
    "ghostship_ai_collection_timestamp_seconds": "When this collection ran.",
    "ghostship_ai_collection_duration_seconds": "How long this collection took.",
    "ghostship_ai_collection_duplicate_series": (
        "How many metric series this collection published twice. The repeats "
        "are dropped, so the file holds one series per name and label set."
    ),
    "ghostship_ai_routing_enabled": (
        "One when the owner's routing switch is on. The collector publishes "
        "the switch and never acts on it itself."
    ),
    "ghostship_ai_static_route_info": (
        "One for every model of the owner's static worker table, with the "
        "role the table gives it and every entry that names it."
    ),
    "ghostship_ai_static_route_remaining_ratio": (
        "The share left of a static route's capacity, read from the routing "
        "snapshot's candidate of that route."
    ),
    "ghostship_ai_static_route_paced_availability": (
        "The Paced Availability of a static route: the pace delta of the "
        "capacity of its candidate."
    ),
    "ghostship_ai_static_route_pace_state": (
        "The band of a static route against the line of its capacity, in the "
        "state label: ahead, on_pace, behind, far_behind, spent or unknown. "
        "One series per row, with the row label plus the state. The line is "
        "the share left minus the route's Paced Availability, and the band "
        "is the value policy's."
    ),
    "ghostship_ai_static_route_reset_timestamp_seconds": (
        "When the capacity window that binds a static route resets."
    ),
    "ghostship_ai_static_route_policy_ok": (
        "One when the runtime policy that carries the static worker routes "
        "was read, zero when it is missing or unreadable."
    ),
    "ghostship_ai_free_provider_selection_info": (
        "One for every free provider, with the model it selected for the "
        "free tier and the basis of that selection."
    ),
    "ghostship_ai_free_provider_selection_remaining_ratio": (
        "The share left of the capacity of the free selection of a provider."
    ),
    "ghostship_ai_free_provider_selection_paced_availability": (
        "The Paced Availability of the free selection of a provider: the "
        "pace delta of the capacity of the route it selected."
    ),
    "ghostship_ai_free_provider_selection_pace_state": (
        "The band of a free provider's selection against the line of its "
        "capacity, in the state label: ahead, on_pace, behind, far_behind, "
        "spent or unknown. One series per free provider, with the provider "
        "label plus the state. The line is the share left minus the "
        "selection's Paced Availability, and the band is the value policy's."
    ),
    "ghostship_ai_free_provider_selection_reset_timestamp_seconds": (
        "When the capacity window that binds the free selection of a "
        "provider resets."
    ),
    "ghostship_ai_provider_free_models": (
        "The free models of a provider, split into the ones that are "
        "available and the ones that are not."
    ),
}

# The picker, discovery and dashboards share this exact selection projection.
for field, description in {
    'info': 'Canonical model selection and availability, with native effort and quota pool.',
    'position': 'Preferred model position across providers in its category.',
    'default': 'One for the canonical native default worker, zero for other selections.',
    'provider_position': 'Preferred model position within its provider and category.',
    'pool_position': 'Preferred model position within its quota pool and category.',
    'quality': 'Integer Quality score; ordering uses the unrounded posterior.',
    'quality_rounds': 'Observed model rounds used by Quality.',
    'quality_accepted': 'Accepted model rounds used by Quality.',
    'remaining_ratio': 'Remaining share of the displayed long or quota limiting window.',
    'pace_delta': 'Weekly or monthly limiting window pace in percentage points.',
    'reset_timestamp_seconds': 'Effective limiting-window reset; reset_source identifies custom resets.',
}.items():
    METRIC_HELP['ghostship_ai_picker_model_' + field] = description

GAUGE_METRICS = tuple(METRIC_HELP)

# How many dropped series a run names. A run that drops a handful of series
# names every one of them; a run that drops many names the first ones and
# says how many it did not name, so the log stays a log and not a dump.
MAX_NAMED_DUPLICATE_SERIES = 20


def log(message: str) -> None:
    print(f"ai-usage: {message}", file=sys.stderr, flush=True)


def resolve_t3_base_url(server_file: str) -> str:
    """Return a T3 base URL the host can reach."""
    raw = Path(server_file).read_text(encoding="utf-8").strip()
    base = ""
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        base = str(data.get("url") or data.get("server") or "").strip()
    elif isinstance(data, str):
        base = data.strip()
    else:
        # The bridge publishes a bare URL, not a JSON object.
        base = raw
    if not base:
        raise ValueError("no T3 server URL")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base)
    host = parts.hostname or ""
    if host and _resolves(host):
        return base
    address = _container_address(host)
    if not address:
        raise ValueError(f"cannot resolve the T3 container address for {host}")
    return urlunsplit((parts.scheme, f"{address}:{parts.port or 80}", parts.path, "", ""))


def _resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except OSError:
        return False
    return True


# The Podman network the T3 Code container is attached to, and the resolver
# that serves its names. The address is looked up here instead of through
# the Podman API: the API is a root equivalent, and the collector has no
# reason to hold it.
PODMAN_NETWORK_FILE = "/etc/containers/networks/ghostship_net.json"
PODMAN_NETWORK = "ghostship_net"


def _container_address(container: str) -> str:
    """Return the address of a container on the Ghostship network.

    The published name of the container is resolved with the resolver of the
    Podman network it is attached to. The Podman API is not used: it is a
    root equivalent, and a name lookup does not need it.
    """
    resolver = _network_resolver()
    if not resolver:
        return ""
    return _resolve_name(container, resolver)


def _network_resolver(network_file: str = PODMAN_NETWORK_FILE) -> str:
    """The address of the resolver that serves the Podman network names."""
    try:
        document = json.loads(Path(network_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(document, dict):
        return ""
    for subnet in document.get("subnets") or []:
        if not isinstance(subnet, dict):
            continue
        gateway = subnet.get("gateway")
        if isinstance(gateway, str) and gateway:
            return gateway
    return ""


def _resolve_name(name: str, resolver: str, timeout: float = 5.0) -> str:
    """Resolve one name with the network resolver."""
    try:
        host = socket.gethostbyname_ex(name)
    except OSError:
        host = None
    if host and host[2]:
        return host[2][0]
    query = bytearray(b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00")
    for part in name.split("."):
        query += bytes([len(part)]) + part.encode("idna") if part.isascii() else bytes([0])
    query += b"\x00\x00\x01\x00\x01"
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        connection.settimeout(timeout)
        try:
            connection.sendto(bytes(query), (resolver, 53))
            answer, _address = connection.recvfrom(1024)
        finally:
            connection.close()
    except OSError:
        return ""
    if len(answer) < 16 or answer[3] & 0x0F:
        return ""
    count = int.from_bytes(answer[6:8], "big")
    offset = 12
    # The question: the name, then the type and the class.
    while offset < len(answer) and answer[offset]:
        offset += 1 + answer[offset]
    offset += 1 + 4
    for _ in range(count):
        if offset + 12 > len(answer):
            return ""
        if answer[offset] & 0xC0 == 0xC0:
            # A compressed name: the type and the class follow it.
            offset += 2
        else:
            while offset < len(answer) and answer[offset]:
                offset += 1 + answer[offset]
            offset += 1
        record_type = int.from_bytes(answer[offset : offset + 2], "big")
        record_length = int.from_bytes(answer[offset + 8 : offset + 10], "big")
        offset += 10
        if record_type == 1 and record_length == 4:
            return ".".join(str(byte) for byte in answer[offset : offset + 4])
        offset += record_length
    return ""


def read_session_token(path: str) -> str:
    """Read the current managed bearer projection, shared with the bridge."""
    return Path(path).read_text(encoding="utf-8").strip()


def collect_t3(now: float, catalog, context: dict[str, Any]) -> list[SourceResult]:
    """Read T3 Code's provider limits and usage history."""
    try:
        base_url = resolve_t3_base_url(T3_SERVER_FILE)
        token = read_session_token(T3_SESSION_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [
            SourceResult(
                source="t3",
                status="missing_credentials",
                reason=codes.UNAVAILABLE,
            )
        ]
    if not token:
        return [
            SourceResult(
                source="t3",
                status="missing_credentials",
                reason=codes.MISSING_CREDENTIALS,
            )
        ]
    try:
        # Historical usage scans can exceed twenty seconds on the live server.
        # Keep the transport default (sixty seconds), bounded per request.
        with T3Client(base_url, token, timeout=60) as client:
            return t3source.collect(client, now, catalog=catalog, context=context)
    except (T3Error, OSError) as error:
        return [
            SourceResult(
                source="t3",
                status="error",
                reason=codes.RPC_FAILED,
            )
        ]


def free_model_samples(
    catalog: catalog_module.Catalog,
    offered: Iterable[tuple[str, str]],
    pool_models: Iterable[tuple[str, str]],
    now: float,
) -> list[Sample]:
    """List every model that can be used at no cost right now."""
    samples: list[Sample] = []
    offered_set = {(provider, model) for provider, model in offered}
    pool_set = {(provider, model) for provider, model in pool_models}
    seen: set[tuple[str, str, str]] = set()
    for provider in ("opencode-go", "opencode", "openrouter", "ollama"):
        for entry in catalog.free_models(provider):
            key = (entry["provider"], entry["model"], entry["tier"])
            if key in seen:
                continue
            seen.add(key)
            labels = {
                "provider": entry["provider"],
                "model": entry["model"],
                "tier": entry["tier"],
                "source": "model_catalog",
            }
            samples.append(("ghostship_ai_free_model", labels, 1.0))
            available = 1.0 if (entry["provider"], entry["model"]) in offered_set else 0.0
            samples.append(("ghostship_ai_free_model_available", labels, available))
            for kind, rate in entry["rates"].items():
                samples.append(
                    (
                        "ghostship_ai_free_model_price_usd_per_mtok",
                        {
                            "provider": entry["provider"],
                            "model": entry["model"],
                            "kind": kind,
                            "source": "model_catalog",
                        },
                        float(rate),
                    )
                )
            samples.append(
                (
                    "ghostship_ai_free_model_observed_timestamp_seconds",
                    labels,
                    now,
                )
            )
    for provider, model in sorted(pool_set):
        key = (provider, model, "free_pool")
        if key in seen:
            continue
        seen.add(key)
        labels = {
            "provider": provider,
            "model": model,
            "tier": "free_pool",
            "source": "free_pool",
        }
        samples.append(("ghostship_ai_free_model", labels, 1.0))
        samples.append(("ghostship_ai_free_model_available", labels, 1.0))
        samples.append(("ghostship_ai_free_model_observed_timestamp_seconds", labels, now))
    return samples


# A cooldown further out than this cannot be true. A millisecond timestamp
# read as seconds lands tens of thousands of years out, and a value like
# that is a broken reading, not a park. It is reported as an issue and it
# never blocks a route.
MAX_COOLDOWN_SECONDS = 366 * 24 * 3600.0

# The providers whose zero-price listing is a free route of its own. The
# OpenRouter free models and the Go subscription's free models cost nothing
# by construction, so they are dedicated free routes and they may hold the
# free tier.
FREE_ROUTE_PROVIDERS = ("opencode-go", "openrouter")

# The providers whose zero-price listing is a promotional route of a paid
# account. It costs nothing right now, it is not a free route of its own,
# and it competes in bulk. A model that is in both sets is a promotional
# route: the promotional zero price is checked first.
PROMO_PROVIDERS = ("opencode", "ollama")


def _published_unlimited_routes(
    catalog: catalog_module.Catalog, inventory: Iterable[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The routes the provider publishes as unlimited.

    The Go documentation lists its free routes as unlimited, and a live
    probe confirmed it: a free route answered while the paid monthly
    window of the plan was spent. The rule is the published one, and the
    catalog may not contradict it: a route the catalog prices is only
    unlimited when it prices it free.
    """
    free_prices = {
        str(entry.get("model") or "")
        for entry in (catalog.free_models(published_module.GO_PROVIDER) or [])
    }
    routes: list[tuple[str, str]] = []
    for provider, model in sorted(inventory or ()):
        if not published_module.unlimited_route(provider, model):
            continue
        entry = catalog.model_entry(provider, model)
        if entry is not None and model not in free_prices:
            # The catalog prices the route and it is not free: the published
            # unlimited listing does not apply to it.
            continue
        routes.append((str(provider), str(model)))
    return routes


def _measured_window_keys(
    measured_windows: Iterable[Mapping[str, Any]],
) -> set[str]:
    """The keys the provider-reported windows occupy.

    A window the provider reports for the whole account is keyed by the
    provider, and the one it reports for a single model by the route. An
    inferred window is filed beside them, never over them.
    """
    keys: set[str] = set()
    for measured in measured_windows or ():
        provider = str(measured.get("provider") or "")
        if not provider:
            continue
        model = str(measured.get("model") or "*")
        keys.add(provider if model == "*" else f"{provider}/{model}")
    return keys


def inferred_windows(
    context: Mapping[str, Any],
    occupied: Iterable[str],
    moment: float,
) -> list[dict[str, Any]]:
    """The windows the limit failures of the routes imply, in filing order.

    The capacity of a route is its own learned window, not its provider's
    silence. A route that was never refused files a "no limit seen" window
    under the provider key; while a refused route of the same provider
    exists, that quiet window is not the provider's capacity and it never
    takes the provider key: the learned window of the refused route is.

    A reported or a published window is never replaced. The keys those
    windows already occupy are given, and an inferred window is skipped when
    the account, the route, or the key itself holds one. The account's
    capacity is the same for every one of its routes, so it is filed once.

    Each entry carries the key it is filed under, the route it came from,
    the model families it applies to, and the window itself. The ranking
    reads the key and the window; the snapshot publishes the account record,
    which keeps the route's model as the scope of a model-scoped limit.
    """
    capacities = context.get("inferred_capacity") or {}
    taken = set(occupied)
    refused = {
        str(capacity.get("provider") or "")
        for capacity in capacities.values()
        if str(capacity.get("state") or "") != usage_inference.STATE_NO_FAILURE
    }
    filed: list[dict[str, Any]] = []
    keys: set[str] = set()
    for route, capacity in sorted(capacities.items()):
        provider, model = str(route[0]), str(route[1])
        state = str(capacity.get("state") or "")
        if state == usage_inference.STATE_NO_FAILURE and provider in refused:
            # A route that was never refused stands behind no budget at
            # all, and it never stands in for a refused route of its
            # provider.
            continue
        key = usage_inference.key_for(capacity)
        if key in taken or provider in taken or f"{provider}/{model}" in taken:
            continue
        if key in keys:
            continue
        keys.add(key)
        filed.append(
            {
                "key": key,
                "provider": provider,
                "model": model,
                "applies_to": (
                    (model,) if str(capacity.get("scope") or "") == "model" else ()
                ),
                "window": usage_inference.window_for(capacity, moment),
            }
        )
    return filed


def provider_limit_samples(
    inputs: Mapping[str, Any],
) -> list[Sample]:
    """The limits of every free provider, with the basis of each reading.

    A limit is published once per basis it was read with: the number the
    provider itself publishes, the ceiling the pool enforces, the number
    the provider's response headers carried, and the fact that a limit
    exists but no number is known for it. The bases are never mixed: a
    reader sees which reading a number came from.
    """
    samples: list[Sample] = []
    pool_providers = set(inputs.get("pool_providers") or ())
    limits = inputs.get("pool_limits") or {}
    for (provider, model, limit, scope), entry in sorted(limits.items()):
        value, basis = entry if isinstance(entry, tuple) else (entry, "configured")
        samples.append(
            (
                "ghostship_ai_provider_limit",
                {
                    "provider": provider,
                    "model": model,
                    "limit": limit,
                    "scope": scope,
                    "basis": basis,
                },
                float(value),
            )
        )
    for provider in sorted(pool_providers):
        for name, value, basis in pool_published.published_limits(provider):
            samples.append(
                (
                    "ghostship_ai_provider_limit",
                    {
                        "provider": provider,
                        "model": "*",
                        "limit": name,
                        "scope": "account",
                        "basis": basis,
                    },
                    float(value),
                )
            )
            samples.append(
                (
                    "ghostship_ai_pool_published_limit",
                    {
                        "provider": provider,
                        "limit": name,
                        "source": pool_published.PUBLISHED_SOURCE,
                        "checked_at": pool_published.PUBLISHED_CHECKED_AT,
                    },
                    float(value),
                )
            )
    return samples


def free_route_accounts(
    results: list[SourceResult],
    context: dict[str, Any],
    measured_windows: list[dict[str, Any]],
) -> set[str]:
    """The accounts that are observed to serve a free route on their own.

    The observation needs three facts at the same time: the paid allowance of
    the account is spent, the account is still ready, and it still offers a
    free model. A provider that is observed in that state is serving the
    free route independently of the paid allowance, so the paid allowance is
    not evidence about the free models of that account.

    It is an observation of the provider's behaviour, with a time, not a
    promise about the provider.
    """
    accounts: set[str] = set()
    ready = {
        str(instance)
        for instance, status in (context.get("instance_status") or {}).items()
        if str(status) == "ready"
    }
    # The instance that serves an account. The OpenCode instance serves
    # several accounts, and only the Go one has the paid allowance.
    instance_of = {
        "opencode-go": "opencode",
        "ollama": "opencode",
        "openrouter": "opencode",
    }
    spent: set[str] = set()
    for window in measured_windows:
        used = window.get("usedRatio")
        if not isinstance(used, (int, float)) or isinstance(used, bool):
            continue
        if float(used) >= 1.0 and str(window.get("kind")) in ("monthly", "weekly", "subscription"):
            spent.add(str(window.get("provider")))
    for account in spent:
        instance = instance_of.get(account, account)
        if instance in ready:
            accounts.add(account)
    return accounts


def ranking_inputs(
    results: list[SourceResult],
    catalog: catalog_module.Catalog,
    context: dict[str, Any],
    measured_windows: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Derive the ranking inputs from what the sources reported."""
    measured_windows = measured_windows or []
    moment = time.time() if now is None else float(now)
    inventory: set[tuple[str, str]] = set()
    for provider, model in context.get("offered_models") or []:
        inventory.add((str(provider), str(model)))
    free: set[tuple[str, str]] = set()
    promo: set[tuple[str, str]] = set()
    external: dict[tuple[str, str], bool] = {}
    usage: dict[tuple[str, str], float] = {}
    pool_providers: set[str] = set()
    pool_models: set[tuple[str, str]] = set()
    quota_used: dict[tuple[str, str, str, str], float] = {}
    quota_reset: dict[tuple[str, str, str, str], float] = {}
    for name, labels, value in _iter_samples(results):
        provider = labels.get("provider", "")
        model = labels.get("model", "")
        if name == "ghostship_ai_pool_model_info":
            inventory.add((provider, model))
            free.add((provider, model))
            pool_providers.add(provider)
            pool_models.add((provider, model))
        elif name == "ghostship_ai_pool_model_available":
            external[(provider, model)] = value > 0
        elif name == "ghostship_ai_free_model":
            # A free route of a free-route provider is a dedicated free
            # route; the zero-price listing of a paid account is a
            # promotional route that competes in bulk.
            if provider in PROMO_PROVIDERS:
                promo.add((provider, model))
            else:
                free.add((provider, model))
        elif name == "ghostship_ai_usage_tokens" and labels.get("window") == "7d":
            key = (provider, model)
            usage[key] = usage.get(key, 0.0) + value
        elif name == "ghostship_ai_quota_used_ratio" and model == "*":
            key = (
                provider,
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_used[key] = value
        elif name == "ghostship_ai_quota_reset_timestamp_seconds" and model == "*":
            key = (
                provider,
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_reset[key] = value
        elif name == "ghostship_ai_quota_used_ratio" and provider == "antigravity" and model != "*":
            # A model quota is more precise than the shared family window.
            key = (
                f"{provider}/{model}",
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_used[key] = value
        elif name == "ghostship_ai_quota_reset_timestamp_seconds" and provider == "antigravity" and model != "*":
            key = (
                f"{provider}/{model}",
                labels.get("account", "default"),
                labels.get("window", "other"),
                labels.get("quota", "default"),
                labels.get("source", ""),
            )
            quota_reset[key] = value
    # The free routes of the T3 accounts, and the promotional zero-price
    # routes of the paid accounts. The two sets are kept apart: a model that
    # is in both is a promotional route, and the promotional zero price is
    # checked before the dedicated free class.
    for provider in FREE_ROUTE_PROVIDERS:
        for entry in catalog.free_models(provider):
            free.add((entry["provider"], entry["model"]))
    for provider in PROMO_PROVIDERS:
        for entry in catalog.free_models(provider):
            promo.add((entry["provider"], entry["model"]))
    windows: dict[str, list[Any]] = {}
    for measured in measured_windows:
        provider = str(measured.get("provider") or "")
        model = str(measured.get("model") or "*")
        used = measured.get("usedRatio")
        reset = measured.get("resetEpoch")
        duration = measured.get("durationSeconds")
        quota_id = str(measured.get("quotaId") or "default")
        # A window the source publishes but does not read is visible and it
        # does not constrain the route: an unknown reading is not evidence
        # that the account is exhausted. The provider stays visible, and the
        # lockout it reports is observed instead of inferred.
        gating = measured.get("gating")
        window = ranking_module.QuotaWindow(
            kind=str(measured.get("kind") or "other"),
            used_ratio=float(used) if isinstance(used, (int, float)) else None,
            reset_epoch=float(reset) if isinstance(reset, (int, float)) else None,
            applies_to=_window_scope(quota_id),
            quota_id=quota_id,
            duration_seconds=(
                float(duration) if isinstance(duration, (int, float)) and duration else None
            ),
            # When the provider last reported the window. A reading that is
            # old is not headroom.
            observed_at=(
                float(measured.get("observedAtEpoch"))
                if isinstance(measured.get("observedAtEpoch"), (int, float))
                else None
            ),
            basis=str(measured.get("basis") or ""),
            # When the entitlement of the window ends, when the provider
            # publishes an end. A promotion without a published end has no
            # end, and that is unknown rather than zero.
            ends_at=(
                float(measured.get("endsAt"))
                if isinstance(measured.get("endsAt"), (int, float))
                else None
            ),
            gating=gating is not False,
            reset_source=str(measured.get("resetSource") or "provider"),
            provider_reset_epoch=measured.get("providerResetEpoch"),
        )
        if model == "*":
            windows.setdefault(provider, []).append(window)
        else:
            # A window the provider reports for one model only.
            windows.setdefault(f"{provider}/{model}", []).append(window)
    # The routes the provider publishes as unlimited. The route carries a
    # window of its own, so it has a stated state instead of no state, and
    # the paid allowance of the account does not gate it. The documentation
    # lists those routes as unlimited "for a limited time", so the basis of
    # the window is a promotion and the end of it is unknown. A free route
    # reaches the collector on two paths, the instance inventory and the
    # catalog's free list, and it is the same route on both: the published
    # listing does not depend on whether the instance offers it today.
    for provider, model in _published_unlimited_routes(
        catalog, set(inventory) | free
    ):
        windows.setdefault(f"{provider}/{model}", []).append(
            ranking_module.QuotaWindow(
                kind="unlimited",
                used_ratio=0.0,
                reset_epoch=None,
                quota_id=published_module.UNLIMITED_QUOTA_ID,
                duration_seconds=None,
                ends_at=published_module.GO_FREE_ENDS_AT,
                observed_at=moment,
                basis=published_module.GO_FREE_BASIS,
            )
        )
    # The capacity the limit failures of a route imply. A route that
    # reports its usage keeps its reported window: an inference never
    # overrides a reported reading, and a route whose account already has a
    # window keeps that one as well. The window is keyed by the route when
    # the limit is the model's own, and by the provider when the limit
    # belongs to the account. A route that was never refused never stands in
    # for a refused route of its provider.
    for inferred in inferred_windows(context, windows, moment):
        windows.setdefault(inferred["key"], []).append(inferred["window"])
    # The free pool's own evidence: the admissions of a route, its limits
    # and its cooldown. The admission is what lets a pool route hold the
    # free tier and take a workload.
    pool_admissions: dict[tuple[str, str, str], bool] = {}
    pool_limits: dict[tuple[str, str, str, str], float] = {}
    pool_cooldowns: dict[tuple[str, str], float] = {}
    pool_last_used: dict[tuple[str, str], float] = {}
    pool_probes: dict[tuple[str, str], dict[str, Any]] = {}
    pool_unavailable_reasons: dict[tuple[str, str], str] = {}
    for name, labels, value in _iter_samples(results):
        pool_provider = str(labels.get("provider") or "")
        pool_model = str(labels.get("model") or "")
        if name == "ghostship_ai_pool_model_admission":
            workload = str(labels.get("workload") or "")
            if workload:
                pool_admissions[(pool_provider, pool_model, workload)] = value > 0
        elif name == "ghostship_ai_pool_limit":
            key = (
                pool_provider,
                pool_model,
                str(labels.get("limit") or ""),
                str(labels.get("scope") or "account"),
            )
            pool_limits[key] = (float(value), "configured")
        elif name == "ghostship_ai_pool_observed_limit":
            # A limit the provider's own response headers carried.
            key = (
                pool_provider,
                pool_model,
                str(labels.get("limit") or ""),
                str(labels.get("scope") or "account"),
            )
            pool_limits.setdefault(key, (float(value), "observed"))
        elif name == "ghostship_ai_pool_model_cooldown_until_seconds":
            pool_cooldowns[(pool_provider, pool_model)] = float(value)
        elif name == "ghostship_ai_pool_route_last_used_timestamp_seconds":
            # When the pool last sent a job to the route. The least recently
            # used route breaks the tie inside the quality band.
            pool_last_used[(pool_provider, pool_model)] = float(value)
        elif name == "ghostship_ai_pool_probe":
            # The pool's own probe of the route: its state and the class of
            # the answer. The moment comes with its own series.
            entry = pool_probes.setdefault(
                (pool_provider, pool_model), {}
            )
            entry["state"] = str(labels.get("state") or "")
            entry["category"] = str(labels.get("category") or "")
        elif name == "ghostship_ai_pool_probe_timestamp_seconds":
            pool_probes.setdefault((pool_provider, pool_model), {})["at"] = float(
                value
            )
        elif name == "ghostship_ai_pool_model_unavailable_reason":
            # The pool's own reason a candidate is unavailable. The snapshot
            # repeats it for a parked route instead of guessing one.
            pool_unavailable_reasons[(pool_provider, pool_model)] = str(
                labels.get("reason") or ""
            )
    # The cooldown is the pool's own evidence that a route is parked. A
    # cooldown that cannot be true is a broken reading, not a park: it is
    # reported as an issue and it never blocks a route.
    provider_cooldown = {
        provider: value
        for (provider, model), value in pool_cooldowns.items()
        if model == "*"
    }
    model_cooldown = {
        key: value
        for key, value in pool_cooldowns.items()
        if key[1] != "*"
    }
    pool_issues: dict[tuple[str, str], list[str]] = {}
    for (pool_provider, pool_model) in sorted(pool_models):
        cooldown = model_cooldown.get(
            (pool_provider, pool_model), provider_cooldown.get(pool_provider)
        )
        if cooldown is None:
            continue
        if cooldown > moment + MAX_COOLDOWN_SECONDS:
            pool_issues.setdefault((pool_provider, pool_model), []).append(
                "invalid_cooldown"
            )
            # The route is not blocked by a cooldown that cannot be true.
            external[(pool_provider, pool_model)] = True
        elif cooldown > moment:
            external[(pool_provider, pool_model)] = False
    pool_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for route in sorted(pool_models):
        pool_evidence.setdefault(
            route, {"admission": [], "limits": [], "issues": []}
        )
    for key, cooldown in sorted(pool_cooldowns.items()):
        pool_evidence.setdefault(
            (key[0], key[1]), {"admission": [], "limits": [], "issues": []}
        )
    for (pool_provider, pool_model, workload), admitted in sorted(pool_admissions.items()):
        entry = pool_evidence.setdefault(
            (pool_provider, pool_model), {"admission": [], "limits": [], "issues": []}
        )
        entry["admission"].append({"workload": workload, "admitted": admitted})
    for (pool_provider, pool_model, limit, scope), value in sorted(pool_limits.items()):
        entry = pool_evidence.setdefault(
            (pool_provider, pool_model), {"admission": [], "limits": [], "issues": []}
        )
        entry["limits"].append(
            {
                "limit": limit,
                "value": value[0],
                "scope": scope,
                "basis": value[1],
            }
        )
    for (pool_provider, pool_model), probe in sorted(pool_probes.items()):
        pool_evidence.setdefault(
            (pool_provider, pool_model), {"admission": [], "limits": [], "issues": []}
        )["probe"] = dict(probe)
    for (pool_provider, pool_model), reason in sorted(
        pool_unavailable_reasons.items()
    ):
        pool_evidence.setdefault(
            (pool_provider, pool_model), {"admission": [], "limits": [], "issues": []}
        )["unavailable_reason"] = reason
    for key, entry in pool_evidence.items():
        # A provider-wide cooldown belongs to every route of that provider.
        cooldown = pool_cooldowns.get(key)
        if cooldown is None:
            cooldown = provider_cooldown.get(key[0])
        entry["cooldown_until"] = cooldown
        entry["issues"] = list(pool_issues.get(key, []))
        # When the pool last used the route. It breaks the tie inside the
        # quality band of the free tier, and it is absent when the pool has
        # no reading for the route.
        entry["last_used"] = pool_last_used.get(key)
        # The pool's own probe of the route, and its reason for parking a
        # candidate. Both are absent when the pool published neither.
        entry["probe"] = pool_probes.get(key)
        entry["unavailable_reason"] = pool_unavailable_reasons.get(key)
    return {
        "inventory": sorted(inventory),
        "free": free,
        "promo": promo,
        "external": external,
        "usage": usage,
        "windows": windows,
        "pool_providers": pool_providers,
        "pool_models": sorted(pool_models),
        "pool_evidence": pool_evidence,
        "pool_issues": pool_issues,
        "pool_limits": pool_limits,
    }


def merge_record_retirements(
    retired: Mapping[str, Mapping[str, Any]],
    record_retirements: Mapping[str, Mapping[str, Any]],
    record_last_success: Mapping[str, float],
) -> dict[str, dict[str, Any]]:
    """Add the retirements the OpenCode request record shows.

    Some retirements reach the collector only through the request record,
    not through T3 Code's run history. They join the same record, keyed by
    "provider/model": a route keeps the earliest moment it was first seen
    retired, and a success the request record shows after that moment
    clears it, as a successful run does.
    """
    merged = {str(route): dict(record) for route, record in (retired or {}).items()}
    for route, record in (record_retirements or {}).items():
        previous = merged.get(route)
        entry = dict(record)
        if previous is not None:
            earlier = float(previous.get("first_seen") or 0.0)
            if earlier and earlier < float(entry.get("first_seen") or 0.0):
                entry["first_seen"] = earlier
        merged[route] = entry
    for route in list(merged):
        succeeded = (record_last_success or {}).get(route)
        if succeeded is None:
            continue
        if float(succeeded) > float(merged[route].get("first_seen") or 0.0):
            merged.pop(route, None)
    return merged


def retired_routes(
    persisted: Mapping[str, Mapping[str, Any]] | None,
    failures: Iterable[Mapping[str, Any]] | None,
    successes: Mapping[str, float] | None,
) -> dict[str, dict[str, Any]]:
    """The routes that are retired, and the moment each was first seen.

    A provider that retired a model does not serve it again, so the
    retirement is not a failure of an hour: it is kept in the collector's
    own state file and outlives the window of the failure that reported it.
    A later successful run of the route clears it: the provider serves the
    model again, and the route is usable once more.

    A retirement is scoped to one route. The other models of the same
    provider are not touched by it.
    """
    found: dict[str, dict[str, Any]] = {
        str(route): dict(record) for route, record in (persisted or {}).items()
    }
    for failure in failures or ():
        if (
            str(failure.get("reason") or "")
            != runtime_state_module.REASON_MODEL_RETIRED
        ):
            continue
        route = str(failure.get("route") or failure.get("target") or "")
        if not route:
            continue
        record = {
            "provider": str(failure.get("provider") or ""),
            "model": str(failure.get("model") or ""),
            "route": route,
            "first_seen": float(failure.get("observed_at") or 0.0),
            "reason": runtime_state_module.REASON_MODEL_RETIRED,
        }
        previous = found.get(route)
        if previous is not None:
            # The retirement started when it was first seen, and a later
            # report of it does not make it younger.
            first_seen = float(previous.get("first_seen") or 0.0)
            if first_seen and (
                not record["first_seen"] or first_seen < record["first_seen"]
            ):
                record["first_seen"] = first_seen
        found[route] = record
    # A later successful run of the route clears the retirement.
    for route in list(found):
        succeeded = (successes or {}).get(route)
        if succeeded is None:
            continue
        if float(succeeded) > float(found[route].get("first_seen") or 0.0):
            found.pop(route, None)
    return found


def _success_window(
    now: float, retired: Mapping[str, Mapping[str, Any]] | None
) -> float:
    """How far back a successful run is read to clear a retirement.

    A successful run that is older than the window of a failure still
    clears a retirement when it is newer than the retirement itself, so
    the window of the successes reaches back to the first retirement the
    collector remembers.
    """
    window = float(runtime_state_module.MAX_AGE_SECONDS)
    first_seen = [
        float(record.get("first_seen") or 0.0)
        for record in (retired or {}).values()
        if record.get("first_seen")
    ]
    if not first_seen:
        return window
    return max(window, float(now) - min(first_seen))


def ranking_samples(
    results: list[SourceResult],
    catalog: catalog_module.Catalog,
    context: dict[str, Any],
    now: float,
    *,
    t3_home: str = T3_HOME,
    state_path: str | None = None,
    aa_cache: dict[str, Any] | None = None,
    aa_3d_cache: dict[str, Any] | None = None,
    t3_state: str = T3_STATE_FILE,
) -> tuple[list[Sample], list[Any]]:
    """Rank every model we can use.

    Returns the ranking metrics and the ranked models themselves, so the
    snapshot can be built from the same ranking.
    """
    measured_windows: list[dict[str, Any]] = []
    for result in results:
        measured_windows.extend(result.windows)
    inputs = ranking_inputs(results, catalog, context, measured_windows, now=now)
    inventory = inputs["inventory"]
    free = inputs["free"]
    promo = inputs["promo"]
    external = inputs["external"]
    usage = inputs["usage"]
    windows = inputs["windows"]
    pool_providers = inputs["pool_providers"]
    context["free_models"] = free
    context["promo_models"] = promo
    context["pool_evidence"] = inputs["pool_evidence"]
    samples: list[Sample] = []
    # The limits of every free provider, with the basis of each reading.
    samples.extend(provider_limit_samples(inputs))
    # A cooldown that cannot be true is an issue, not a park. The route is
    # not blocked by it, and the issue is published so a reader sees it.
    for (provider, model), issues in sorted((inputs.get("pool_issues") or {}).items()):
        for issue in issues:
            samples.append(
                (
                    "ghostship_ai_pool_cooldown_invalid",
                    {"provider": provider, "model": model, "issue": issue},
                    1.0,
                )
            )
    three_d_scores: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        three_d = threed_module.collect(t3_home, catalog, inventory, now) or {}
    except (OSError, ValueError) as error:
        log(f"3D usage could not be read ({type(error).__name__})")
        three_d = {}
    for (provider, model), entry in three_d.items():
        if provider in pool_providers:
            # The 3D tier holds our frontier and bulk models; the free pool
            # belongs to the free tier.
            continue
        tokens = int(entry.get("tokens", 0))
        measured_3d = aa_3d.lookup(aa_3d_cache, provider, model)
        three_d_scores[(provider, model)] = {
            "usage_tokens": tokens,
            "elo": measured_3d.get("elo"),
            "source": measured_3d.get("source"),
            "observed_at": measured_3d.get("observed_at"),
            # A model belongs in the 3D tier only when the catalog proves it
            # can look at an image. The workload admission is verified at the
            # snapshot, where the durable evidence lives. A high token count
            # is not evidence of 3D work, and there is no 3D prior.
            "eligible": threed_module.visual_capable(
                catalog.model_entry(provider, model) if catalog is not None else None
            ),
        }
        samples.extend(
            threed_module.three_d_samples(provider, model, tokens=tokens, now=now)
        )
    rank_kwargs: dict[str, Any] = {
        "models": [
            ranking_module.ModelRecord(provider=provider, model=model)
            for provider, model in inventory
        ],
        "catalog": catalog,
        "quota_windows": windows,
        "free_models": free,
        "promo_models": promo,
        "external_availability": external,
        "usage_tokens": usage,
        "three_d_scores": three_d_scores,
        "aa_cache": aa_cache,
        "native_models": context.get("native_models") or {},
        "now": now,
        "state_path": state_path,
    }
    if "exclude_providers" in inspect.signature(ranking_module.rank_models).parameters:
        # The free inference pool belongs to the free tier, not to the bulk
        # tier of the paid accounts.
        rank_kwargs["exclude_providers"] = {"bulk": sorted(pool_providers)}
    if "promo_models" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["promo_models"] = sorted(promo)
    if "external_availability" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["external_availability"] = external
    if "free_route_accounts" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["free_route_accounts"] = sorted(
            free_route_accounts(results, context, measured_windows)
        )
    if "frontier_workhorses" in inspect.signature(ranking_module.rank_models).parameters:
        # The owner's list of frontier workhorses comes from the runtime
        # policy, so the producer and the reader share one list.
        rank_kwargs["frontier_workhorses"] = sorted(
            OWNER_POLICY.get("frontierPrimeModels") or ()
        )
    # The observed failures of the routes, read from the T3 Code state. A
    # route that is known to be broken does not win a tier, and it stays
    # visible with the reason and the moment it was observed.
    #
    # The routes whose model a provider retired are kept in the collector's
    # own state file: the retirement outlives the window of the failure
    # that reported it.
    persisted = ranking_module.retired_from_state(
        ranking_module.load_state(state_path)
    )
    observations = runtime_state_module.read_observations(
        t3_state, now, success_age_seconds=_success_window(now, persisted)
    )
    observed_failures = observations["failures"]
    retired = retired_routes(persisted, observed_failures, observations["successes"])
    retired = merge_record_retirements(
        retired,
        context.get("inferred_retirements") or {},
        context.get("inferred_last_success") or {},
    )
    if "retired_routes" in inspect.signature(ranking_module.rank_models).parameters:
        rank_kwargs["retired_routes"] = retired
    for failure in observed_failures:
        samples.append(
            (
                "ghostship_ai_route_unavailable",
                {
                    "scope": str(failure.get("scope") or ""),
                    "target": str(failure.get("target") or ""),
                    "reason": str(failure.get("reason") or ""),
                },
                1.0,
            )
        )
        observed_at = failure.get("observed_at")
        if isinstance(observed_at, (int, float)) and not isinstance(observed_at, bool):
            samples.append(
                (
                    "ghostship_ai_route_unavailable_observed_timestamp_seconds",
                    {
                        "scope": str(failure.get("scope") or ""),
                        "target": str(failure.get("target") or ""),
                        "reason": str(failure.get("reason") or ""),
                    },
                    float(observed_at),
                )
            )
    context["observed_failures"] = observed_failures
    context["ranking_inventory"] = sorted(inventory)
    ranked = ranking_module.rank_models(**rank_kwargs)
    samples.extend(
        ranking_module.rank_samples(
            ranked,
            now=now,
            native_models=context.get("native_models") or {},
            aa_cache=aa_cache,
            catalog=catalog,
        )
    )
    return samples, ranked


def read_facts(facts_path: str | None) -> dict[str, Any]:
    """The durable facts of the models, out of the facts file.

    The facts have their own file, so the ranking state and the facts never
    write over each other.
    """
    if not facts_path:
        return {}
    try:
        document = json.loads(Path(facts_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(document, dict):
        return {}
    facts = document.get("facts")
    return facts if isinstance(facts, dict) else {}


def model_identities_path(explicit: str | None, runtime_policy: str | None) -> str:
    """The model identities file: the one named, or the one beside the policy.

    The runtime policy and the model identities ship together in the
    owner's policy tree, so the default is the identities file in the
    directory of the runtime policy. With neither, there is no file.
    """
    if explicit:
        return str(explicit)
    if runtime_policy:
        return str(Path(runtime_policy).parent / MODEL_IDENTITIES_FILE)
    return ""


def read_outcomes(
    *,
    identities_path: str | None = None,
    runtime_policy: str | None = None,
    ledger: str | None = None,
    backfill: str | None = None,
) -> dict[str, Any]:
    """The trust of the models and the rounds that were observed.

    Four files are read, and none of them is written: the model
    identities, the runtime policy that carries the owner's trust, the
    delegation ledger, and its backfill.

    Every reading is total. A file that is missing, unreadable or empty is
    an empty history, and a model that nothing speaks about is trusted.
    """
    policy: dict[str, Any] = {}
    if runtime_policy:
        try:
            document = json.loads(Path(runtime_policy).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            document = None
        if isinstance(document, dict):
            policy = document
    return {
        "identities": outcomes_module.load_identities(identities_path),
        "policy": policy,
        "rounds": outcomes_module.read_ledger(ledger),
        "backfill": outcomes_module.load_backfill(backfill),
    }


def build_snapshot(
    results: list[SourceResult],
    ranked: list[Any],
    context: dict[str, Any],
    now: float,
    aa_cache: dict[str, Any] | None = None,
    measured_windows: list[dict[str, Any]] | None = None,
    catalog: Any = None,
    facts: dict[str, Any] | None = None,
    aa_3d_cache: dict[str, Any] | None = None,
    free_models: set[tuple[str, str]] | None = None,
    promo_models: set[tuple[str, str]] | None = None,
    outcomes: Mapping[str, Any] | None = None,
    routing_enabled: bool = False,
) -> dict[str, Any]:
    """Build the canonical ranking and eligibility snapshot."""
    sources = []
    for result in results:
        observed = result.observed_at
        sources.append(
            {
                "id": result.source,
                "status": result.status,
                "reason": codes.reason(result.reason),
                "observed_at": (
                    None
                    if observed is None
                    else datetime.fromtimestamp(observed, tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                ),
                "observed_at_epoch": observed,
                "last_success_at": (
                    datetime.fromtimestamp(now, tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                    if result.ok
                    else None
                ),
            }
        )
    snapshot = snapshot_module.build_snapshot(
        now=now,
        sources=sources,
        ranked=ranked,
        native_models=context.get("native_models") or {},
        policy=OWNER_POLICY,
        aa_cache=aa_cache,
        measured_windows=measured_windows,
        catalog=catalog,
        facts=facts,
        aa_3d_cache=aa_3d_cache,
        free_models=free_models or set(),
        promo_models=promo_models or set(),
        pool_evidence=context.get("pool_evidence") or {},
        # The probe of every route the OpenCode record shows. The snapshot
        # takes the newer of it and the pool's own probe.
        t3_probes=context.get("t3_probes") or {},
        inventory=context.get("ranking_inventory") or [],
        # The learned windows of the routes whose limit failures measured
        # them. The account section publishes them beside the reported
        # readings, never over one, and a refused route keeps its record
        # even while it has no ranked row.
        inferred_windows=inferred_windows(
            context, _measured_window_keys(measured_windows or []), now
        ),
        # The trust of the models and the rounds they were measured on.
        # Without them every model is trusted and no round was observed.
        outcomes=outcomes,
        routing_enabled=bool(routing_enabled),
    )
    if isinstance(snapshot, dict):
        snapshot["announced_resets"] = context.get("announced_resets") or {
            "schema": 1, "status": "not_checked", "announcements": []}
        quota_block = snapshot.setdefault("quota", {})
        if isinstance(quota_block, dict):
            quota_block["entitlements"] = quota_module.entitlements(
                measured_windows or [], now
            )
            for entry in quota_block['entitlements']:
                if pools.not_used_window(str(entry.get('provider') or ''), entry):
                    entry['not_used'] = True
    if isinstance(snapshot, dict):
        policy = (outcomes or {}).get("policy") or {}
        orchestrators = (policy.get("roles") or {}).get("orchestrator") or []
        # An unreadable policy/identity source cannot authorize picker writes.
        # Publish no selection, so every settings consumer refuses the document.
        if outcomes is None or model_selection.policy_ready(outcomes):
            snapshot["model_selection"] = model_selection.build(snapshot, orchestrators, evidence=outcomes)
    return snapshot


def collect(
    now: float | None = None,
    *,
    t3_home: str = T3_HOME,
    secrets_env: str = SECRETS_ENV_FILE,
    pool_server: str = POOL_SERVER_FILE,
    pool_token: str = POOL_TOKEN_FILE,
    pool_ledger: str | None = POOL_LEDGER_FILE,
    catalog_path: str = CATALOG_FILE,
    state_path: str | None = None,
    events_cache: str = EVENTS_CACHE_FILE,
    opencode_db: str = OPENCODE_DB_FILE,
    window_state_path: str | None = providers_module.OLLAMA_WINDOW_STATE_FILE,
    t3_state: str = T3_STATE_FILE,
    aa_cache: dict[str, Any] | None = None,
    aa_3d_cache: dict[str, Any] | None = None,
    custom_resets: list[dict[str, Any]] | None = None,
    announcements: dict[str, Any] | None = None,
) -> tuple[list[SourceResult], list[Sample], dict[str, Any]]:
    """Run every source and return the results, the extra samples, and the context."""
    moment = wall_clock() if now is None else now
    catalog = catalog_module.Catalog.load(catalog_path)
    context: dict[str, Any] = {}
    results: list[SourceResult] = []
    results.extend(collect_t3(moment, catalog, context))
    results.append(providers_module.read_grok(f"{t3_home}", moment))
    results.append(providers_module.read_opencode_go(f"{t3_home}", moment))
    results.append(providers_module.read_antigravity(f"{t3_home}", moment))
    # Our own requests of the last minute, counted from the T3 Code state.
    # A provider that publishes a per-minute limit and does not report it is
    # measured against this count, and the count is marked as such.
    request_counts = runtime_state_module.read_request_counts(t3_state, moment)
    results.append(
        providers_module.read_openrouter(
            secrets_env,
            moment,
            requests_last_minute=request_counts.get("openrouter"),
        )
    )
    results.append(
        providers_module.read_ollama(secrets_env, moment, state_path=window_state_path)
    )
    results.extend(pool_module.collect(pool_server, pool_token, pool_ledger, moment, home=t3_home))

    extra: list[Sample] = []
    ranked: list[Any] = []
    pool_models = {
        (labels.get("provider", ""), labels.get("model", ""))
        for name, labels, _value in _iter_samples(results)
        if name == "ghostship_ai_pool_model_info"
    }
    offered = context.get("offered_models") or []
    extra.extend(free_model_samples(catalog, offered, pool_models, moment))
    # The request records of the routes, and the capacity they imply. The
    # two records are read at the same time and each of them caps itself, so
    # the pair never holds the collector up. A record that cannot be read
    # contributes no events: the routes it would have fed keep the basis
    # they had.
    routes = _known_routes(offered, pool_models, extra)
    inferred = usage_inference.read_and_infer(
        moment,
        opencode_db=opencode_db,
        events_cache=events_cache,
        pool_ledger=pool_ledger,
        routes=routes,
    )
    results.extend(inferred.results)
    context["announced_resets"] = announcements or {"schema": 1, "status": "not_checked", "announcements": []}
    reset_overrides.apply(results, announced_resets.overrides(results, context["announced_resets"], moment), moment)
    reset_overrides.apply(results, custom_resets or [], moment)
    context["inferred_capacity"] = inferred.capacities
    context["inferred_retirements"] = dict(inferred.retirements)
    context["inferred_last_success"] = dict(inferred.last_success)
    context["t3_probes"] = dict(inferred.probes)
    context["inference_unmatched"] = dict(inferred.unmatched)
    ranking_metrics, ranked = ranking_samples(
        results,
        catalog,
        context,
        moment,
        t3_home=t3_home,
        state_path=state_path,
        aa_cache=aa_cache,
        aa_3d_cache=aa_3d_cache,
        t3_state=t3_state,
    )
    extra.extend(ranking_metrics)
    context["ranked"] = ranked
    return results, extra, context


def _known_routes(
    offered: Iterable[tuple[str, str]],
    pool_models: Iterable[tuple[str, str]],
    samples: Iterable[Sample],
) -> set[tuple[str, str]]:
    """The routes the collector knows.

    The inventory of the instance, the routes of the free pool and the free
    list of the catalog. An event of a route that is not in this set cannot
    be placed on a route, and it is counted and published as unmatched: a
    reading never invents a route.
    """
    routes = {(str(provider), str(model)) for provider, model in offered or ()}
    routes |= {(str(provider), str(model)) for provider, model in pool_models or ()}
    for name, labels, _value in samples or ():
        if name == "ghostship_ai_free_model":
            routes.add((str(labels.get("provider") or ""), str(labels.get("model") or "")))
    return routes


def _iter_samples(results: Iterable[SourceResult]):
    for result in results:
        yield from result.metrics


def feed_samples(snapshot: Mapping[str, Any]) -> list[Sample]:
    """The state of the Artificial Analysis pull, and what it found.

    The pull runs once a day, and a model that is new or whose measurement
    changed is the trigger for a re-ranking. The names are published so a
    reader can see which models the last pull brought in.
    """
    samples: list[Sample] = []
    quality = snapshot.get("quality_feed") or {}
    status = str(quality.get("status") or "missing")
    records = quality.get("records")
    samples.append(
        (
            "ghostship_ai_feed_status",
            {
                "source": "artificialanalysis",
                "status": status,
                "reason": str(quality.get("reason") or ""),
            },
            float(records) if isinstance(records, (int, float)) else 0.0,
        )
    )
    coverage = snapshot.get("aa_coverage") or {}
    states = coverage.get("states") or {}
    for state, count in sorted(states.items()):
        samples.append(
            (
                "ghostship_ai_feed_status",
                {
                    "source": "artificialanalysis",
                    "status": str(state),
                    "reason": "",
                },
                float(count) if isinstance(count, (int, float)) else 0.0,
            )
        )
    for entry in coverage.get("new_models") or ():
        if not isinstance(entry, Mapping):
            continue
        samples.append(
            (
                "ghostship_ai_model_new",
                {
                    "provider": str(entry.get("provider") or ""),
                    "model": str(entry.get("model") or ""),
                },
                1.0,
            )
        )
    for entry in coverage.get("changed_models") or ():
        if not isinstance(entry, Mapping):
            continue
        samples.append(
            (
                "ghostship_ai_model_changed",
                {
                    "provider": str(entry.get("provider") or ""),
                    "model": str(entry.get("model") or ""),
                },
                1.0,
            )
        )
    return samples


def trust_samples(snapshot: Mapping[str, Any]) -> list[Sample]:
    """The trust of every model, and the outcomes it was measured on.

    The trust is published per tier, because the trust of a model is read
    for the task type of the tier it holds. The reason is published with
    it, so a reader sees why a route is held back instead of only that it
    is. The outcome is published as its own fields, so the prior, the
    observed rounds and the quality can be read apart.
    """
    samples: list[Sample] = []
    for row in snapshot.get("candidates") or []:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider or not model:
            continue
        for tier, record in (row.get("trust") or {}).items():
            if not isinstance(record, Mapping):
                continue
            samples.append(
                (
                    "ghostship_ai_model_trust_info",
                    {
                        "provider": provider,
                        "model": model,
                        "tier": str(tier),
                        "task_type": str(record.get("task_type") or ""),
                        "level": str(record.get("level") or "trusted"),
                        "source": str(record.get("source") or "default"),
                        "reason": str(record.get("reason") or ""),
                    },
                    1.0,
                )
            )
        for tier, record in (row.get("outcome") or {}).items():
            if not isinstance(record, Mapping):
                continue
            for field in ("p0", "k", "n", "s", "p"):
                value = record.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                samples.append(
                    (
                        "ghostship_ai_model_outcome",
                        {
                            "provider": provider,
                            "model": model,
                            "tier": str(tier),
                            "task_type": str(record.get("task_type") or ""),
                            "field": field,
                        },
                        float(value),
                    )
                )
        # The display score is one number per model, so neither series
        # carries a tier: every page reads the same score of the same model.
        score = row.get("quality_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            samples.append(
                (
                    "ghostship_ai_model_quality_score",
                    {
                        "provider": provider,
                        "model": model,
                        "basis": str(row.get("quality_basis") or ""),
                    },
                    float(score),
                )
            )
        for field in ("n", "s"):
            value = row.get(f"quality_{field}")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                samples.append(
                    (
                        "ghostship_ai_model_quality_rounds",
                        {"provider": provider, "model": model, "field": field},
                        float(value),
                    )
                )
    return samples


def decision_input_samples(
    snapshot: Mapping[str, Any],
) -> list[Sample]:
    """The inputs a decision was made on, as gauges.

    The benchmark condition and the execution reasoning are two different
    statements and both are published: the condition is what the benchmark
    measured, the reasoning is what the owner's policy proposes to run. The
    window that binds the capacity and the window that binds the pace are
    published apart, and the frontier membership carries its wait and its
    reset.
    """
    samples: list[Sample] = []
    for row in snapshot.get("candidates") or []:
        if not isinstance(row, Mapping):
            continue
        provider = str(row.get("provider") or "")
        model = str(row.get("model") or "")
        if not provider or not model:
            continue
        labels = {"provider": provider, "model": model}
        aa = row.get("aa") or {}
        condition = aa.get("condition") or {}
        measured_variant = str(condition.get("measured_variant") or "")
        if measured_variant:
            samples.append(
                (
                    "ghostship_ai_model_aa_condition",
                    {
                        **labels,
                        "variant": measured_variant,
                        "confirmed": (
                            "confirmed" if condition.get("confirmed") else "unconfirmed"
                        ),
                    },
                    1.0,
                )
            )
        execution = aa.get("execution") or {}
        default = str(execution.get("default") or "")
        escalation = str(execution.get("escalation") or "")
        if default or escalation:
            samples.append(
                (
                    "ghostship_ai_model_execution_reasoning",
                    {
                        **labels,
                        "default": default,
                        "escalation": escalation,
                        "supported": str(execution.get("state") or ""),
                    },
                    1.0,
                )
            )
        capacity = row.get("capacity") or {}
        capacity_binding = str(capacity.get("capacity_binding_id") or "")
        if capacity_binding:
            samples.append(
                (
                    "ghostship_ai_model_capacity_binding",
                    {**labels, "window": capacity_binding},
                    1.0,
                )
            )
        pace_binding = str(capacity.get("pace_binding_id") or "")
        if pace_binding:
            samples.append(
                (
                    "ghostship_ai_model_pace_binding",
                    {**labels, "window": pace_binding},
                    1.0,
                )
            )
        three_d = row.get("three_d") or {}
        elo = three_d.get("elo")
        if isinstance(elo, (int, float)) and not isinstance(elo, bool):
            samples.append(
                ("ghostship_ai_three_d_elo", labels, float(elo))
            )
        value_3d = (row.get("value_3d") or {}).get("value")
        if isinstance(value_3d, (int, float)) and not isinstance(value_3d, bool):
            samples.append(
                (
                    "ghostship_ai_model_value_3d",
                    {
                        **labels,
                        "cost_source": str(
                            (row.get("value_3d") or {}).get("cost_source") or ""
                        ),
                        "proxy": (
                            "proxy" if (row.get("value_3d") or {}).get("proxy") else "measured"
                        ),
                    },
                    float(value_3d),
                )
            )
        reserve = row.get("reserve") or {}
        if reserve.get("3d"):
            for tier in reserve.get("tiers") or ():
                samples.append(
                    (
                        "ghostship_ai_model_reserved",
                        {
                            **labels,
                            "tier": str(tier),
                            "reserve": "3d",
                            "withheld": (
                                "withheld" if reserve.get("withheld") else "ordered_last"
                            ),
                        },
                        1.0,
                    )
                )
    frontier = (snapshot.get("coverage") or {}).get("frontier") or {}
    for member in frontier.get("eligible") or ():
        if not isinstance(member, Mapping):
            continue
        labels = {
            "provider": str(member.get("provider") or ""),
            "model": str(member.get("model") or ""),
        }
        samples.append(
            (
                "ghostship_ai_frontier_member",
                {**labels, "state": str(member.get("state") or "")},
                1.0,
            )
        )
        wait = member.get("seconds_to_reset")
        if isinstance(wait, (int, float)) and not isinstance(wait, bool):
            samples.append(
                ("ghostship_ai_frontier_wait_seconds", labels, float(wait))
            )
    return samples


def render(
    results: list[SourceResult],
    extra: list[Sample],
    now: float,
    duration: float,
    snapshot: dict[str, Any] | None = None,
    runtime_policy: str | None = None,
) -> str:
    writer = MetricWriter()

    def add(name, labels, value):
        provider = str(labels.get('provider') or labels.get('account') or '')
        if pools.not_used_window(provider, labels):
            usage = name.startswith(('ghostship_ai_quota_', 'ghostship_ai_account_window_'))
            if not usage or ('pace' in name and not name.endswith('_pace_state')) or 'expected_' in name:
                return
            labels = {**labels, 'not_used': 'true'}
            if name.endswith('_pace_state'):
                labels['state'] = 'not_used'
        writer.add(name, labels, value)

    for name, help_text in METRIC_HELP.items():
        writer.declare(name, "gauge", help_text)
    for result in results:
        provider = result.source
        add(
            "ghostship_ai_source_success",
            {"source": result.source, "provider": provider},
            1.0 if result.ok else 0.0,
        )
        add(
            "ghostship_ai_source_status",
            {
                "source": result.source,
                "provider": provider,
                "status": result.status,
                "reason": codes.reason(result.reason),
            },
            1.0,
        )
        if result.observed_at is not None:
            add(
                "ghostship_ai_source_observed_timestamp_seconds",
                {"source": result.source, "provider": provider},
                result.observed_at,
            )
        add(
            "ghostship_ai_source_duration_seconds",
            {"source": result.source, "provider": provider},
            result.duration_s,
        )
        if result.ok:
            add(
                "ghostship_ai_source_last_success_timestamp_seconds",
                {"source": result.source, "provider": provider},
                now,
            )
    for provider, source in COVERAGE:
        add(
            "ghostship_ai_provider_coverage",
            {"provider": provider, "source": source},
            1.0,
        )
    for result in results:
        for name, labels, value in result.metrics:
            add(name, labels, value)
    for name, labels, value in extra:
        add(name, labels, value)
    for name, labels, value in model_selection.samples((snapshot or {}).get("model_selection") or {}):
        add(name, labels, value)
    for name, labels, value in snapshot_module.decision_samples(snapshot or {}):
        add(name, labels, value)
    for name, labels, value in snapshot_module.provider_capacity_samples(snapshot or {}):
        add(name, labels, value)
    for name, labels, value in snapshot_module.account_window_samples(snapshot or {}):
        add(name, labels, value)
    for name, labels, value in feed_samples(snapshot or {}):
        add(name, labels, value)
    for name, labels, value in trust_samples(snapshot or {}):
        add(name, labels, value)
    for name, labels, value in decision_input_samples(snapshot or {}):
        add(name, labels, value)
    # The name the collector already publishes for a model, so a static row
    # says what the model is. The row falls back to the model id.
    display_names: dict[tuple[str, str], str] = {}
    for name, labels, _value in list(_iter_samples(results)) + list(extra):
        if name != "ghostship_ai_model_info":
            continue
        provider = str(labels.get("provider") or "")
        model = str(labels.get("model") or "")
        text = str(labels.get("name") or "")
        if provider and model and text:
            display_names[(provider, model)] = text
    for name, labels, value in static_routes_module.samples(
        runtime_policy, snapshot or {}, display_names
    ):
        add(name, labels, value)
    # The free selection of every free provider, and the free models it
    # holds, read from the same snapshot.
    for name, labels, value in free_selection_module.samples(
        snapshot or {}, display_names
    ):
        add(name, labels, value)
    # The availability of every account: whether it can serve right now, why
    # not when it cannot, and where its limit comes from.
    for name, labels, value in account_availability_module.samples(snapshot or {}, now):
        add(name, labels, value)
    # The place every card takes on the Providers page. The page draws the
    # cards in this order, and the order is the owner's.
    for name, labels, value in card_order_module.samples(snapshot or {}):
        add(name, labels, value)
    measured: list[dict[str, Any]] = []
    for result in results:
        measured.extend(result.windows)
    for name, labels, value in quota_module.quota_pace_samples(measured, now):
        add(name, labels, value)
    for name, labels, value in quota_module.entitlement_samples(measured, now):
        add(name, labels, value)
    for name, labels, value in quota_module.entitlement_display_samples(measured, now):
        add(name, labels, value)
    add("ghostship_ai_collection_timestamp_seconds", {}, now)
    add("ghostship_ai_collection_duration_seconds", {}, duration)
    # A series is published once. A repeat is dropped and counted, and the
    # count is published, so a duplicate never passes unnoticed. The run
    # names every series it dropped, so the emitter that published a series
    # twice can be found, and it says whether the repeat carried the value
    # that was kept.
    for dropped in writer.dropped[:MAX_NAMED_DUPLICATE_SERIES]:
        log(
            f"dropped repeated series {dropped.describe()}"
            f" ({'same' if dropped.same_value else 'different'} value)"
        )
    unnamed = len(writer.dropped) - MAX_NAMED_DUPLICATE_SERIES
    if unnamed > 0:
        log(f"and {unnamed} more")
    add(
        "ghostship_ai_collection_duplicate_series", {}, float(writer.duplicates)
    )
    # The owner's routing switch, published as it is. The gauge carries no
    # label: the switch is one switch for the whole snapshot.
    add(
        "ghostship_ai_routing_enabled",
        {},
        1.0 if ((snapshot or {}).get("routing") or {}).get("enabled") else 0.0,
    )
    return writer.render()


def write_output(path: str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o644)
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect AI usage and limit metrics.")
    parser.add_argument(
        "--output",
        default="/var/lib/ghostship-container-metrics/ai-usage.prom",
        help="Where to write the Prometheus textfile.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print instead of writing a file.")
    parser.add_argument('--model-selection-preferences', default='',
                        help='Versioned exact native worker-build choices per provider.')
    parser.add_argument("--now", type=float, default=None, help="Override the current time.")
    parser.add_argument(
        "--state",
        default="/var/lib/ghostship-ai-usage/state.json",
        help="Where the model ranking keeps its evaluation state.",
    )
    parser.add_argument(
        "--window-state",
        default=providers_module.OLLAMA_WINDOW_STATE_FILE,
        help=(
            "Where the collector remembers the reset instants of the windows "
            "whose length it has to learn from them."
        ),
    )
    parser.add_argument(
        "--events-cache",
        default=EVENTS_CACHE_FILE,
        help=(
            "Where the reader of the OpenCode request records keeps its own "
            "cache of the events it read."
        ),
    )
    parser.add_argument(
        "--projection",
        action="append",
        default=[],
        help=(
            "An extra runtime presentation of the same snapshot bytes, for a "
            "consumer that reads a shared directory. Repeatable."
        ),
    )
    parser.add_argument(
        "--facts",
        default=FACTS_PATH,
        help="The durable facts of the models, written by the daily procedure.",
    )
    parser.add_argument(
        "--aa-catalog",
        default=CATALOG_FILE,
        help="The public model catalog, for the provider listed prices.",
    )
    parser.add_argument(
        "--aa-cache",
        default=AA_CACHE_PATH,
        help="The cached Artificial Analysis feed, written by the daily procedure.",
    )
    parser.add_argument(
        "--aa-3d-cache",
        default=AA_3D_CACHE_PATH,
        help=(
            "The bounded Artificial Analysis 3D snapshot (Elo, source, date and "
            "benchmark conditions), written by the pull of the public pages. "
            "Absent means no 3D rank."
        ),
    )
    parser.add_argument(
        "--snapshot",
        default=SNAPSHOT_PATH,
        help="Where the canonical ranking and eligibility snapshot is written.",
    )
    parser.add_argument(
        "--routing-enabled",
        choices=("true", "false"),
        default="false",
        help=(
            "The owner's routing switch. The collector publishes it to its "
            "consumers and never acts on it itself."
        ),
    )
    parser.add_argument(
        "--runtime-policy",
        default="",
        help=(
            "The runtime policy that carries the owner's static worker "
            "routes. A missing or unreadable file publishes no static rows "
            "and says so; the rest of the collection is unaffected."
        ),
    )
    parser.add_argument(
        "--model-identities",
        default="",
        help=(
            "The model identities: which routes serve one model. The "
            "default is the model-identities.json beside the runtime "
            "policy. A missing file is no identity at all."
        ),
    )
    parser.add_argument(
        "--delegation-ledger",
        default=DELEGATION_LEDGER_FILE,
        help=(
            "The delegation ledger: the rounds that were observed. It is "
            "opened read only, and a missing ledger is an empty history."
        ),
    )
    parser.add_argument(
        "--delegation-backfill",
        default=DELEGATION_BACKFILL_FILE,
        help=(
            "The rounds the ledger does not carry, and the rounds whose "
            "verdict it corrects. A missing file is no round at all."
        ),
    )
    parser.add_argument("--reconcile-picker", action="store_true",
                        help="Synchronize managed model favorites and the worker default through authenticated RPC.")
    parser.add_argument("--custom-resets", default="/var/lib/ghostship-ai-usage/custom-resets.json",
                        help="Owner overrides; published explicitly as custom resets.")
    parser.add_argument("--announced-resets", default=announced_resets.PATH,
                        help="Public announcements recorded by the bounded Desktop check.")
    parser.add_argument("--picker-state", default="/var/lib/ghostship-ai-usage/picker.json",
                        help="Ownership journal for managed T3 model favorites.")
    args = parser.parse_args(argv)

    worker_builds = model_selection.load_worker_builds(args.model_selection_preferences)
    started = time.monotonic()
    routing_enabled = args.routing_enabled == "true"
    log(f"the routing switch is {'on' if routing_enabled else 'off'}")
    now = wall_clock() if args.now is None else args.now
    aa_cache = aa.load_cache(args.aa_cache, now)
    aa_3d_cache = aa_3d.load_cache(args.aa_3d_cache, now)
    results, extra, context = collect(
        now,
        state_path=args.state,
        window_state_path=args.window_state,
        events_cache=args.events_cache,
        aa_cache=aa_cache,
        aa_3d_cache=aa_3d_cache,
        custom_resets=reset_overrides.load(args.custom_resets),
        announcements=announced_resets.load(args.announced_resets),
    )
    duration = time.monotonic() - started
    measured: list[dict[str, Any]] = []
    for result in results:
        measured.extend(result.windows)
    catalog = catalog_module.Catalog.load(args.aa_catalog)
    outcomes = read_outcomes(
        # The model identities sit beside the runtime policy, unless the
        # caller names another file.
        identities_path=model_identities_path(
            args.model_identities, args.runtime_policy
        ),
        runtime_policy=args.runtime_policy,
        ledger=args.delegation_ledger,
        backfill=args.delegation_backfill,
    )
    if args.model_selection_preferences:
        outcomes['policy'].setdefault('model_selection', {})['worker_builds'] = worker_builds
    snapshot = build_snapshot(
        results,
        context.get("ranked") or [],
        context,
        now,
        aa_cache=aa_cache,
        measured_windows=measured,
        catalog=catalog,
        facts=read_facts(args.facts),
        free_models=context.get("free_models") or set(),
        promo_models=context.get("promo_models") or set(),
        aa_3d_cache=aa_3d_cache,
        outcomes=outcomes,
        routing_enabled=routing_enabled,
    )
    text = render(
        results,
        extra,
        now,
        duration,
        snapshot,
        runtime_policy=args.runtime_policy,
    )
    if args.stdout:
        sys.stdout.write(text)
        sys.stdout.write(json.dumps(snapshot, indent=1, default=str) + "\n")
    else:
        write_output(args.output, text)
        log(f"wrote {len(text)} bytes to {args.output}")
    # The snapshot is the canonical answer for a consumer, so it is always
    # written, atomically, even in the dry run. A write that fails is an
    # error: the unit must fail visibly, never pass with a stale file.
    written = snapshot_module.write_snapshot(args.snapshot, snapshot)
    log(f"wrote {written} bytes to {args.snapshot}")
    for path, size in snapshot_module.publish(snapshot, args.projection):
        log(f"wrote {size} bytes to {path}")
    if args.reconcile_picker:
        from ghostship_t3.bridge import Bridge
        from ghostship_t3.model_selection import reconcile
        bridge = Bridge(server=resolve_t3_base_url(T3_SERVER_FILE),
                        bearer=read_session_token(T3_SESSION_FILE))
        reconciliation = reconcile(snapshot, bridge, args.picker_state)
        log(f"picker: {reconciliation['state']}; {reconciliation['favorite_changes']} favorite changes")
    for result in results:
        log(f"{result.source}: {result.status} ({codes.reason(result.reason)})")
    log(f"wrote {len(text)} bytes to {'stdout' if args.stdout else args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
