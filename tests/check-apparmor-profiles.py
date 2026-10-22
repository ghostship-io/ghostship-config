#!/usr/bin/env python3
"""Fail when an AppArmor profile names more exec transitions than the budget.

apparmor_parser 5.x keeps at most 12 distinct named exec transition
targets in one profile block. A profile that names a thirteenth one is
refused as a whole ("Profile X has too many specified profile
transitions"), the policy load fails, and the kernel keeps the previous
policy: the host silently runs the old rules. The check counts the named
transitions of every profile block and fails above the budget, so a
profile the kernel would refuse can never pass CI.

The budget is per profile block, because that is what the parser counts:
the limits live in one profile's exec table, not in the file.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/apparmor"

# The named exec transition targets one profile block may hold.
TRANSITION_BUDGET = 12

# A profile block starts a line with its name. Nested blocks are the
# profile's own children, and each child is a profile of its own.
PROFILE_HEADER = re.compile(r"^profile\s+(\S+)")

# The exec modes that name a profile: px, Px, pux, PUx, cx, Cx, ux, Ux,
# pix, Pix, cix, Cix, rix, Rix, mix, Mix, fix, Fix and lix, Lix. The
# change_profile rule does not name an exec transition: the parser keeps
# it out of the exec table, so it does not use up the budget.
EXEC_MODE = (
    r"(?:[pP][uU][xX]|[pP][iI][xX]|[cC][iI][xX]|[rR][iI][xX]|[mM][iI][xX]"
    r"|[fF][iI][xX]|[lL][iI][xX]|[pP][xX]|[cC][xX]|[uU][xX])"
)
TRANSITION = re.compile(r"\b" + EXEC_MODE + r"\s*->\s*([^\s,]+)")


def named_transitions(text: str) -> list[tuple[str, int]]:
    """The distinct named transition targets of every profile block.

    Returns the block's name and the number of distinct targets it names.
    A target that appears in several rules counts once, because the
    parser keeps one entry per name in the profile's exec table.
    """
    blocks: list[tuple[str, set[str]]] = []
    stack: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        header = PROFILE_HEADER.match(stripped)
        if header:
            name = header.group(1)
            stack.append(name)
            blocks.append((name, set()))
            continue
        if stripped == "}":
            if stack:
                stack.pop()
            continue
        if stack:
            blocks[-1][1].update(TRANSITION.findall(stripped))
    return [(name, len(targets)) for name, targets in blocks]


def budget_violations(text: str, budget: int = TRANSITION_BUDGET) -> list[tuple[str, int]]:
    """The profile blocks that name more transitions than the budget allows.

    TODO(#102): the budget is not enforced yet, so the check cannot fail a
    profile that the kernel would refuse. The implementation follows.
    """
    return []


def self_test() -> list[str]:
    """The fixtures hold the budget and the parser to the same boundary."""
    failures: list[str] = []
    accepted = FIXTURES / "at-transition-limit.profile"
    refused = FIXTURES / "too-many-transitions.profile"
    for fixture in (accepted, refused):
        if not fixture.is_file():
            failures.append(f"the fixture {fixture.name} is missing")
    if failures:
        return failures

    over = budget_violations(accepted.read_text())
    if over:
        name, count = over[0]
        failures.append(
            f"{accepted.name} names {count} transitions in {name} and must pass "
            f"the {TRANSITION_BUDGET} transition budget")
    under = budget_violations(refused.read_text())
    if not under:
        failures.append(
            f"{refused.name} names 13 transitions and must fail the "
            f"{TRANSITION_BUDGET} transition budget")
    elif under[0][1] != 13:
        failures.append(
            f"{refused.name} names {under[0][1]} transitions and must name 13")
    return failures


def main() -> int:
    failures = self_test()
    for failure in failures:
        print(f"apparmor profile check: {failure}")
    if failures:
        print(f"apparmor profile check: {len(failures)} failure(s)")
        return 1
    print("apparmor profile check: the transition budget holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
