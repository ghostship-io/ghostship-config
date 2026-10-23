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

The outcome value is the third family: the quality the ranking is valued by
is an outcome-weighted quality ``p``, not the raw intelligence index. The
prior ``p0`` places the measured intelligence inside its own tier, ``p``
shrinks that prior toward the outcomes that were actually measured, and the
value combines ``p`` with the efficiency ``E`` under the same weights. The
trust of a route then scales the value, and a free route may lead while it
is close enough to the best available one. The maths lives here, so the ranking
only calls it: no second scorer.
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

# The strength of the prior, in outcomes: k measured outcomes move the prior
# by k / (k + n) of the distance toward the measured outcome rate.
OUTCOME_PRIOR_STRENGTH = 10

# The prior of a tier: where the measured intelligence sits between the
# lowest and the highest intelligence of the models it is compared with.
OUTCOME_PRIOR_FLOOR = 0.5
OUTCOME_PRIOR_CEILING = 0.9
OUTCOME_PRIOR_SPAN = OUTCOME_PRIOR_CEILING - OUTCOME_PRIOR_FLOOR

# A free route leads while its quality is within this margin of the best
# available model: it need not be the best, it is close enough to cost nothing.
FREE_ROUTE_MARGIN = 0.10

# The basis of the display score: which inputs built the number. The score is
# one number per model, so the basis names the measurements that were there
# and the prior that stood in for the ones that were not.
QUALITY_BASIS_AA_OUTCOMES = "AA + outcomes"
QUALITY_BASIS_AA_ONLY = "AA only"
QUALITY_BASIS_OUTCOMES_DEFAULT = "outcomes + default prior"
QUALITY_BASIS_DEFAULT = "default prior"

# The factor the value of an untrusted route is multiplied by.
UNTRUSTED_VALUE_FACTOR = 0.5

# The trust levels of a route, in rank order: a lower rank is more trusted.
TRUST_LEVELS: tuple[str, ...] = ("trusted", "backup", "untrusted", "excluded")


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


def outcome_prior(intelligence: Any, i_min: Any, i_max: Any) -> float:
    """The prior p0 of a model's quality: its intelligence inside its tier.

    The tier is the cohort the model is compared with, so the same index
    reads high in a weak tier and low in a strong one. A missing index has
    no position in the tier and gets the middle of the range; a tier of one
    model has no spread to read, so it gets the ceiling rather than a
    division by zero. The result is clamped to the range.
    """
    index = _finite(intelligence)
    if index is None:
        return OUTCOME_PRIOR_FLOOR
    lowest = _finite(i_min)
    highest = _finite(i_max)
    if lowest is None or highest is None:
        return OUTCOME_PRIOR_FLOOR
    if highest <= lowest:
        return OUTCOME_PRIOR_CEILING
    prior = OUTCOME_PRIOR_FLOOR + OUTCOME_PRIOR_SPAN * (index - lowest) / (highest - lowest)
    return max(OUTCOME_PRIOR_FLOOR, min(OUTCOME_PRIOR_CEILING, prior))


def _outcome_count(value: Any, name: str) -> int:
    number = _finite(value)
    if number is None or number != int(number):
        raise ValueError(f"{name} must be a whole outcome count, not {value!r}")
    return int(number)


def outcome_quality(
    p0: Any, n: Any, s: Any, k: Any = OUTCOME_PRIOR_STRENGTH
) -> float:
    """The quality p: the prior shrunk toward the measured outcomes.

    ``p = (k * p0 + s) / (k + n)``, where ``s`` of ``n`` outcomes succeeded
    and ``k`` outcomes of prior strength stand behind p0. A count that
    cannot exist is a caller error, not an unknown: it raises rather than
    producing a quality that was never measured.
    """
    prior = _finite(p0)
    if prior is None:
        raise ValueError(f"the prior must be a number, not {p0!r}")
    outcomes = _outcome_count(n, "n")
    successes = _outcome_count(s, "s")
    if outcomes < 0 or successes < 0 or successes > outcomes:
        raise ValueError(
            f"an outcome count must satisfy 0 <= s <= n, not s={successes} and n={outcomes}"
        )
    strength = _finite(k)
    if strength is None or strength <= 0.0:
        raise ValueError(f"the prior strength must be a positive number, not {k!r}")
    return (strength * prior + successes) / (strength + outcomes)


def quality_score(
    p0: Any, n: Any, s: Any, k: Any = OUTCOME_PRIOR_STRENGTH
) -> int:
    """The display score of a model: its outcome quality as an integer 0..100.

    The score is the same quality the ranking is valued by, rounded to an
    integer so every page reads one comparable number::

        score = round(100 * (k * p0 + s) / (k + n))

    The prior p0 and the counts n and s are the global ones: the intelligence
    of the model inside the range of every ranked model, not of its tier, and
    the rounds of every task type. The score is therefore one number per
    model, and it never depends on the tier it is read in. A count that
    cannot exist raises, exactly as it does in ``outcome_quality``.
    """
    return int(round(100.0 * outcome_quality(p0, n, s, k)))



def outcome_value(quality: Any, efficiency: Any) -> float | None:
    """The value of a model: the outcome-weighted quality and the efficiency.

    The quality takes the intelligence slot of the policy's weights, so the
    published value and this one cannot drift apart. A missing component
    leaves the value unknown, exactly as the measured value does.
    """
    p = _finite(quality)
    e = _finite(efficiency)
    if p is None or e is None:
        return None
    value, _missing = combine(
        {"intelligence": p, "cost_per_task": e}, VALUE_WEIGHTS
    )
    return value


def trust_rank(level: Any) -> int:
    """The rank of a trust level: trusted 0, backup 1, untrusted 2, excluded 3.

    An absent or unknown level ranks as trusted: the policy grants no
    penalty to a route nobody has judged.
    """
    name = level if isinstance(level, str) else None
    if name is None:
        return TRUST_LEVELS.index("trusted")
    try:
        return TRUST_LEVELS.index(name)
    except ValueError:
        return TRUST_LEVELS.index("trusted")


def trust_adjusted_value(value: Any, level: Any) -> float | None:
    """The value of a route under its trust level.

    An untrusted route keeps half of its value; every other level, and an
    unknown one, leaves it alone. A missing value stays missing.
    """
    number = _finite(value)
    if number is None:
        return None
    if trust_rank(level) == TRUST_LEVELS.index("untrusted"):
        return number * UNTRUSTED_VALUE_FACTOR
    return number


def free_route_leads(quality: Any, best_quality: Any) -> bool:
    """Whether a free route leads against the best available quality.

    A free route leads while it is no more than the margin behind the best
    available model of its trust level: it costs nothing, so being close is
    enough. A missing quality on either side cannot lead.
    """
    p = _finite(quality)
    best = _finite(best_quality)
    if p is None or best is None:
        return False
    return best - p <= FREE_ROUTE_MARGIN


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
        "outcome": {
            "prior": (
                "p0 = 0.5 + 0.4 * (I - I_min) / (I_max - I_min); 0.5 when I "
                "is missing, 0.9 when the tier holds one model, clamped to "
                "[0.5, 0.9]"
            ),
            "quality": "p = (k * p0 + s) / (k + n)",
            "value": "value = 0.70 * p + 0.30 * E",
            "components": {
                "p0": "the measured intelligence inside the tier's range",
                "p": "the prior shrunk toward s of n measured outcomes",
                "E": "the efficiency of the measured cost per task",
            },
            "prior_strength": OUTCOME_PRIOR_STRENGTH,
            "prior_range": [OUTCOME_PRIOR_FLOOR, OUTCOME_PRIOR_CEILING],
            "free_route_margin": FREE_ROUTE_MARGIN,
            "untrusted_value_factor": UNTRUSTED_VALUE_FACTOR,
            "requires": (
                "a quality and an efficiency; a missing one leaves the value "
                "unknown, and 0 <= s <= n is required"
            ),
        },
        "trust": {
            "levels": list(TRUST_LEVELS),
            "order": {level: rank for rank, level in enumerate(TRUST_LEVELS)},
            "unknown": "an absent or unknown level ranks as trusted",
            "value": (
                "an untrusted route keeps untrusted_value_factor of its "
                "value; every other level leaves it unchanged"
            ),
            "untrusted_value_factor": UNTRUSTED_VALUE_FACTOR,
        },
        "renormalized": False,
        "basis": (
            "both measurements are required and nothing is renormalized: a "
            "missing input leaves the value unknown"
        ),
    }
