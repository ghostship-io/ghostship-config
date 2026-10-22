"""The value policy of the ranking: one place, no second scorer.

The owner decides the weights and the transform; the code applies them. The
policy lives here, in one module, so a lead can set a weight without a
change anywhere else: the ranking, the snapshot, the published calculation
and the metrics all read these constants.

Two value families exist:

* the value of a model for ordinary work (the frontier, bulk and free
  tiers): the measured intelligence and the measured cost per task;
* the value of a model for 3D work: the measured intelligence, the
  measured AA-3D capability and the measured cost per task.

Both are a weighted sum of measured inputs, and every input is required. A
missing input leaves the value unknown: nothing is renormalized and no
component is dropped to make a number appear.

The cost transform is swappable. The default is the reciprocal
``1 / (1 + cost)``, which needs no cohort. The other two need the cohort of
the models it is compared with, and they publish their bounds, so a reader
can see what the numbers were relative to.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

# The weights of the value of a model for ordinary work.
VALUE_WEIGHTS: dict[str, float] = {
    "intelligence": 0.70,
    "cost_per_task": 0.30,
}

# The weights of the value of a model for 3D work. The 3D capability is the
# measured AA-3D Elo under the source's published normalization, and the
# intelligence is beside it: the owner asked for the two together, not for
# one to replace the other.
VALUE_3D_WEIGHTS: dict[str, float] = {
    "intelligence": 0.45,
    "three_d": 0.25,
    "cost_per_task": 0.30,
}

# The transforms the cost input may use. The default is the reciprocal; the
# other two need the cohort and publish their bounds.
COST_TRANSFORM_INVERSE = "inverse"
COST_TRANSFORM_MINMAX = "minmax"
COST_TRANSFORM_MEDIAN_RELATIVE = "median_relative"

COST_TRANSFORMS: dict[str, str] = {
    COST_TRANSFORM_INVERSE: "E = 1 / (1 + the Artificial Analysis cost per task in USD)",
    COST_TRANSFORM_MINMAX: (
        "E = 1 - (cost - the cheapest cost of the cohort) / (the dearest cost "
        "of the cohort - the cheapest cost of the cohort); the cohort bounds "
        "are published with the value"
    ),
    COST_TRANSFORM_MEDIAN_RELATIVE: (
        "E = the median cost of the cohort / (the median cost of the cohort + "
        "cost); the cohort median is published with the value"
    ),
}

# The transform the collector uses. A change here changes every value, and
# the transform in force is published with the snapshot and the metrics.
DEFAULT_COST_TRANSFORM = COST_TRANSFORM_INVERSE


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def cost_cohort(costs: Iterable[Any]) -> list[float]:
    """The known costs of the models a value is compared with."""
    cohort: list[float] = []
    for value in costs or ():
        number = _finite(value)
        if number is None or number < 0.0:
            continue
        cohort.append(number)
    return sorted(cohort)


def median(values: Sequence[float]) -> float | None:
    """The median of a list of numbers, or None when it is empty."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def cost_transform(
    cost: Any,
    cohort: Sequence[float] = (),
    transform: str = DEFAULT_COST_TRANSFORM,
) -> tuple[float | None, dict[str, Any]]:
    """The efficiency component E of one cost per task.

    The result is the value and the evidence it was built from: the
    transform that was used and, for the transforms that need a cohort, the
    bounds of that cohort. A cost that is not a number has no efficiency.
    """
    number = _finite(cost)
    if number is None or number < 0.0:
        return None, {"transform": transform, "basis": "no cost per task"}
    name = str(transform or DEFAULT_COST_TRANSFORM)
    if name == COST_TRANSFORM_MINMAX:
        known = [value for value in cohort]
        if len(known) < 2:
            return None, {
                "transform": name,
                "basis": "the cohort has no spread, so the relative scale is unknown",
            }
        lowest = min(known)
        highest = max(known)
        if highest <= lowest:
            return None, {
                "transform": name,
                "basis": "every model of the cohort costs the same, so the relative scale is unknown",
            }
        value = 1.0 - (number - lowest) / (highest - lowest)
        return max(0.0, min(1.0, value)), {
            "transform": name,
            "basis": "the relative scale of the cohort",
            "cohort_min": lowest,
            "cohort_max": highest,
            "cohort_size": len(known),
        }
    if name == COST_TRANSFORM_MEDIAN_RELATIVE:
        middle = median(list(cohort))
        if middle is None or middle <= 0.0:
            return None, {
                "transform": name,
                "basis": "the cohort has no median, so the relative scale is unknown",
            }
        value = middle / (middle + number)
        return max(0.0, min(1.0, value)), {
            "transform": name,
            "basis": "the cost relative to the median cost of the cohort",
            "cohort_median": middle,
            "cohort_size": len(cohort),
        }
    value = 1.0 / (1.0 + number)
    return max(0.0, min(1.0, value)), {
        "transform": COST_TRANSFORM_INVERSE,
        "basis": "the reciprocal of the cost per task; no cohort is needed",
    }


def combine(
    components: Mapping[str, Any], weights: Mapping[str, float]
) -> tuple[float | None, list[str]]:
    """The weighted sum of the measured components.

    Every component is required. A missing one leaves the value unknown
    rather than dropping its weight and renormalizing the rest.
    """
    missing: list[str] = []
    for name in weights:
        value = components.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            missing.append(name)
    if missing:
        return None, missing
    total = sum(float(weights[name]) * float(components[name]) for name in weights)
    return total, []


def policy_document(transform: str = DEFAULT_COST_TRANSFORM) -> dict[str, Any]:
    """The published policy: the weights, the transform and the transforms."""
    name = str(transform or DEFAULT_COST_TRANSFORM)
    if name not in COST_TRANSFORMS:
        name = DEFAULT_COST_TRANSFORM
    return {
        "value": {
            "formula": "0.70 * I + 0.30 * E",
            "weights": dict(VALUE_WEIGHTS),
            "components": {
                "intelligence": "the verified intelligence index over 100",
                "cost_per_task": "the efficiency of the measured cost per task",
            },
            "transform": COST_TRANSFORMS[name],
            "cost_transform": name,
            "requires": "both measurements; a missing cost per task leaves the value unknown",
            "not_aa_claim": "the weights are an owner policy; the inputs are the feed's",
        },
        "value_3d": {
            "formula": "0.45 * I + 0.25 * T + 0.30 * E",
            "weights": dict(VALUE_3D_WEIGHTS),
            "components": {
                "intelligence": "the verified intelligence index over 100",
                "three_d": (
                    "the AA-3D Elo under the source's own published "
                    "normalization, min-max over the complete AA-3D snapshot"
                ),
                "cost_per_task": "the efficiency of the measured cost per task",
            },
            "transform": COST_TRANSFORMS[name],
            "cost_transform": name,
            "requires": (
                "all three measurements; a missing capability or a missing "
                "cost leaves the value unknown"
            ),
        },
        "cost_transforms": dict(COST_TRANSFORMS),
        "cost_transform_in_force": name,
        "renormalized": False,
        "basis": (
            "both measurements are required and nothing is renormalized: a "
            "missing input leaves the value unknown"
        ),
    }
