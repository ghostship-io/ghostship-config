"""One AA/observed quality score for selection and the model-quality table.

Evidence joins the exact native model and recorded effort. Unattributed work
never becomes evidence for the model's current default effort.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Mapping

from metrics import ExactLabel
import aa_bind
import aa as aa_module

MIN_OUTCOMES = 5
PRIOR_STRENGTH = 10
MAX_AGE = 30 * 86400
AA_SOURCE = "https://artificialanalysis.ai/leaderboards/models"


def number(value: Any) -> float | None:
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


def read_evidence(now: float) -> tuple[list[dict], str]:
    """Use the shared producer's validated store; absence is visible, not fatal."""
    try:
        from ghostship_t3.models import read_evidence as read
    except ImportError:
        return [], "producer_unavailable"
    try:
        rows = read(now=now)
    except (OSError, ValueError, TypeError):
        return [], "unreadable"
    return rows, "ok" if rows else "no_evidence"


def blend(aa: float | None, n: int, passed: int) -> dict[str, Any]:
    observed = 100 * passed / n if n else None
    effective = max(0, n - MIN_OUTCOMES + 1)
    weight = effective / (effective + PRIOR_STRENGTH)
    overall = (aa * (1 - weight) + observed * weight if aa is not None and observed is not None
               else aa if aa is not None else observed if n >= MIN_OUTCOMES else None)
    return {"overall": overall, "aa": aa, "observed": observed,
            "observed_weight": weight if aa is not None else (1.0 if n >= MIN_OUTCOMES else 0.0),
            "n": n, "passed": passed,
            "basis": "AA + observed" if aa is not None and effective else
                     "AA only" if aa is not None else "observed only" if n >= MIN_OUTCOMES else "no evidence yet",
            "provisional": n < MIN_OUTCOMES}


def efforts(candidate: Mapping[str, Any]) -> list[tuple[str | None, str]]:
    for option in (candidate.get("native") or {}).get("options") or []:
        if str(option.get("id")).lower() not in ("effort", "reasoningeffort", "variant", "thinking"):
            continue
        if option.get("id") == "thinking" and option.get("type") == "boolean":
            return [("thinking", "true"), ("thinking", "false")]
        values = [value for value in option.get("values") or [] if isinstance(value, str) and value]
        if values:
            return [(str(option["id"]), value) for value in values]
    return [(None, "default")]


def build(candidates: list[dict], records: list[dict], now: float, state: str = "ok",
          prior_cache: Mapping[str, Any] | None = None) -> dict:
    groups = defaultdict(list)
    seen = set()
    for record in records:
        date = number(record.get("date"))
        identity = (record.get("source"), record.get("id"))
        if (record.get("schema_version") != 1 or record.get("source") not in ("bench", "work")
                or not isinstance(record.get("passed"), bool) or not identity[1] or identity in seen
                or date is None or not 0 <= now - date <= MAX_AGE):
            continue
        seen.add(identity)
        groups[(record.get("provider"), record.get("model"), record.get("effort_option"),
                record.get("effort"))].append(record)
    rows = []
    for candidate in candidates:
        native = candidate.get("native") or {}
        provider = native.get("provider_instance_id") or candidate["provider"]
        model = native.get("model_id") or candidate["model"]
        aa = candidate.get("aa") or {}
        prior = number((aa.get("indices") or {}).get("intelligence")) if aa.get("state") == "measured" else None
        aa_date, aa_state = aa.get('fetched_at'), aa.get('state')
        if (prior is None and (prior_cache or {}).get('status') in ('ok','stale')
                and prior_cache.get('index_version') == aa_module.INTELLIGENCE_INDEX_VERSION):
            binding = aa_bind.resolve(prior_cache.get('records') or [], candidate['provider'],
                                      candidate['model'], mode='reference')
            if binding.get('state') == 'measured':
                prior = number(((binding.get('record') or {}).get('indices') or {}).get('intelligence_index'))
                aa_date, aa_state = prior_cache.get('fetched_at'), prior_cache['status']
        prior = min(100.0, prior) if prior is not None else None
        supported = efforts(candidate)
        actual = [(key[2], key[3]) for key in groups if key[:2] == (provider, model)]
        variants = list(dict.fromkeys(supported + actual))
        candidate_rows = []
        for option, effort in variants:
            # Only safe catalog/known effort labels leave the private evidence store.
            if not isinstance(effort, str) or len(effort) > 64:
                continue
            if (option, effort) not in supported and effort not in (
                    "default", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
                continue
            tasks = groups[(provider, model, option, effort)]
            count = len(tasks)
            passed = sum(task["passed"] for task in tasks)
            merged = [task["merged"] for task in tasks if isinstance(task.get("merged"), bool)]
            wall = [number(task.get("wall_seconds")) for task in tasks]
            tokens = [number(task.get("tokens")) for task in tasks]
            times = [value for value in wall if value is not None]
            dates = [task["date"] for task in tasks]
            row = {"provider": candidate["provider"], "model": candidate["model"],
                   "display_name": candidate.get("display_name") or candidate["model"],
                   "effort_option": option, "effort": effort, "selectable": (option, effort) in supported,
                   **blend(prior, count, passed),
                   "aa_source": AA_SOURCE if prior is not None else None, "aa_date": aa_date,
                   "aa_state": aa_state or 'missing',
                   "sources": sorted({task["source"] for task in tasks}),
                   "first_date": min(dates) if dates else None, "date": max(dates) if dates else None,
                   "merged": sum(merged) if merged else None, "merge_n": len(merged),
                   "median_seconds": median(times) if times else None,
                   "seconds_per_pass": sum(wall) / passed if passed and all(v is not None for v in wall) else None,
                   "tokens_per_pass": sum(tokens) / passed if passed and all(v is not None for v in tokens) else None,
                   # Shared pool observations are not task-attributed quota costs.
                   "quota_per_pass": None, "review_findings": None}
            candidate_rows.append(row)
            rows.append(row)
        candidate["quality_evidence"] = candidate_rows
    rows.sort(key=lambda row: (row["overall"] is None, -(row["overall"] or 0),
                               row["provider"], row["model"], row["effort"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return {"schema": "ghostship.model-quality/v1", "state": state, "minimum_outcomes": MIN_OUTCOMES,
            "prior_strength": PRIOR_STRENGTH, "rows": rows}


def choose(candidate: Mapping[str, Any], preferred: list[dict]) -> dict | None:
    rows = [row for row in candidate.get("quality_evidence") or [] if row["selectable"]]
    if not rows:
        return None
    # An unmeasured effort must not erase established results for the model.
    qualified = [row for row in rows if row['n'] >= MIN_OUTCOMES]
    rows = qualified or rows
    wanted = str(preferred[0]["value"]).lower() if preferred else "default"
    return min(rows, key=lambda row: (row["overall"] is None, -(row["overall"] or 0),
                                     (row['seconds_per_pass'] if row['seconds_per_pass'] is not None else
                                      row['median_seconds'] if row['median_seconds'] is not None else math.inf)
                                     if row['passed'] else math.inf,
                                     row["effort"] != wanted, row["effort"]))


def annotate(quality: dict, selection: Mapping[str, Any]) -> None:
    """Publish active membership and one ranked representative per model."""
    active, preferred, selected, billing = set(), {}, set(), {}
    for category in ('worker','orchestrator'):
        for row in selection.get(category) or []:
            key = (row['provider'],row['model'])
            billing[key] = row.get('billing') or 'unknown'
            evidence = row.get('quality_evidence')
            if evidence is not None:
                preferred.setdefault(key,evidence)
            if (row['available'] and row['selection_eligible']
                    and (row['picker_eligible'] or row.get('billing') in ('free','promotion'))
                    and row['trust_level'] not in ('excluded','untrusted')):
                active.add(key)
            chosen = ((selection.get('providers') or {}).get(row['provider']) or {}).get('selected') or {}
            if row.get('native') is not None and row['native'] == chosen.get(category):
                selected.add(key)
            if category == 'worker' and row['key'] == (selection.get('free_selected') or {}).get(row['provider']):
                selected.add(key)
    groups = defaultdict(list)
    for row in quality.get('rows') or []:
        groups[(row['provider'],row['model'])].append(row)
    models = []
    for key, rows in groups.items():
        for row in rows:
            row['billing'] = billing.get(key, 'unknown')
        usable = [row for row in rows if row['selectable']] or rows
        measured = [row for row in usable if row['n']]
        qualified = [row for row in measured if row['n'] >= MIN_OUTCOMES]
        pool = qualified or measured or usable
        representative = preferred.get(key)
        if representative is None or representative not in pool:
            representative = min(pool,
                key=lambda row:(row['overall'] is None,-(row['overall'] or 0),-row['n'],
                                row['median_seconds'] if row['median_seconds'] is not None else math.inf,row['effort']))
        for row in rows:
            row.update(active=key in active, model_selected=key in selected,
                       representative=row is representative)
        models.append(representative)
    models.sort(key=lambda row:(row['overall'] is None,-(row['overall'] or 0),row['provider'],row['model']))
    active_rank = 0
    for rank, representative in enumerate(models,1):
        if representative['active']:
            active_rank += 1
        for row in groups[(representative['provider'],representative['model'])]:
            row.update(model_rank=rank,active_rank=active_rank if representative['active'] else None)


FIELDS = ("overall", "aa", "observed", "observed_weight", "n", "passed", "rank", "merged", "merge_n",
          "median_seconds", "seconds_per_pass", "tokens_per_pass", "quota_per_pass", "review_findings", "date",
          "active", "model_selected", "representative", "model_rank", "active_rank")


def samples(quality: Mapping[str, Any]) -> list:
    values = []
    for row in quality.get("rows") or []:
        labels = {key: ExactLabel(str(row.get(key) or "")) for key in
                  ("provider", "model", "display_name", "effort", "effort_option", "basis", "aa_date", "aa_state", "billing")}
        labels.update(source=ExactLabel(" + ".join(row["sources"]) or "none"),
                      evidence_state=str(quality.get("state") or "no_evidence"))
        values.append(("ghostship_ai_quality_info", labels, 1.0))
        for field in FIELDS:
            raw = row.get(field)
            value = float(raw) if isinstance(raw,bool) else number(raw)
            if value is not None:
                values.append(("ghostship_ai_quality_" + field, dict(labels), value))
    return values
