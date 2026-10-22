#!/usr/bin/env python3
"""Parse every AppArmor profile the host loads, and hold the transition budget.

apparmor_parser 5.x keeps at most 12 distinct named exec transition
targets in one profile block. A profile that names a thirteenth one is
refused as a whole ("Profile X has too many specified profile
transitions"), the policy load fails, and the kernel keeps the previous
policy: the host runs the old rules without saying so. PR #167 broke the
agent desktop policy that way, and the check that only parsed six
profiles never noticed.

The check therefore does three things:

  - it parses every policy that nixosConfigurations.chill-penguin loads,
    exactly as the host renders it and with the include paths the host
    resolves <tunables/global> and the abstractions against, so a profile
    the kernel would refuse can never pass CI;
  - it counts the named transitions of every profile block in those
    policies and fails above the budget, so an author sees the budget
    before it runs out;
  - it holds every profile file in the repository to a policy or to the
    allowlist below, so a new file cannot slip past the check.

The budget is per profile block, because that is what the parser counts:
the limits live in one profile's exec table, not in the file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/apparmor"

# The host whose loaded policies the check parses.
HOST = "chill-penguin"

# The named exec transition targets one profile block may hold.
TRANSITION_BUDGET = 12

# The count from which a policy is reported, so an author sees the budget
# before it runs out.
REPORT_AT = 10

# The repository file each policy is rendered from. The modules that
# build the policies are modules/self-hosted/apparmor.nix (the container
# default, Plex, the hooks and ntfy), modules/self-hosted/
# container-apparmor.nix (the per-container policies) and
# modules/self-hosted/agent-desktop.nix (the agent desktop).
POLICY_SOURCES: dict[str, str] = {
    "ghostship-agent-desktop": "modules/self-hosted/agent-desktop-apparmor.profile",
    "ghostship-bazarr": "modules/self-hosted/apparmor/bazarr.profile",
    "ghostship-chaptarr": "modules/self-hosted/apparmor/chaptarr.profile",
    "ghostship-cloudflared": "modules/self-hosted/apparmor/cloudflared.profile",
    "ghostship-container-default": "modules/self-hosted/container-default-apparmor.profile",
    "ghostship-flaresolverr": "modules/self-hosted/apparmor/flaresolverr.profile",
    "ghostship-github-coordinator": "modules/self-hosted/apparmor/ghostship-github-coordinator.profile",
    "ghostship-gluetun": "modules/self-hosted/apparmor/gluetun.profile",
    "ghostship-grafana": "modules/self-hosted/apparmor/grafana.profile",
    "ghostship-grimmory": "modules/self-hosted/apparmor/grimmory.profile",
    "ghostship-grimmory-db": "modules/self-hosted/apparmor/grimmory-db.profile",
    "ghostship-homepage": "modules/self-hosted/apparmor/homepage.profile",
    "ghostship-hooks": "modules/self-hosted/hooks-apparmor.profile",
    "ghostship-muximux": "modules/self-hosted/apparmor/muximux.profile",
    "ghostship-ntfy": "modules/self-hosted/ntfy-apparmor.profile",
    "ghostship-nzbget": "modules/self-hosted/apparmor/nzbget.profile",
    "ghostship-plex": "modules/self-hosted/plex-apparmor.profile",
    "ghostship-plex-auto-languages": "modules/self-hosted/apparmor/plex-auto-languages.profile",
    "ghostship-private-integrations": "modules/self-hosted/apparmor/ghostship-private-integrations.profile",
    "ghostship-prowlarr": "modules/self-hosted/apparmor/prowlarr.profile",
    "ghostship-pyload": "modules/self-hosted/apparmor/pyload.profile",
    "ghostship-qbittorrent": "modules/self-hosted/apparmor/qbittorrent.profile",
    "ghostship-radarr": "modules/self-hosted/apparmor/radarr.profile",
    "ghostship-recyclarr": "modules/self-hosted/apparmor/recyclarr.profile",
    "ghostship-romm": "modules/self-hosted/apparmor/romm.profile",
    "ghostship-romm-db": "modules/self-hosted/apparmor/romm-db.profile",
    "ghostship-seerr": "modules/self-hosted/apparmor/seerr.profile",
    "ghostship-sonarr": "modules/self-hosted/apparmor/sonarr.profile",
    "ghostship-tautulli": "modules/self-hosted/apparmor/tautulli.profile",
    "ghostship-tdarr": "modules/self-hosted/apparmor/tdarr.profile",
    "ghostship-uptime-kuma": "modules/self-hosted/apparmor/uptime-kuma.profile",
    "ghostship-victorialogs": "modules/self-hosted/apparmor/victorialogs.profile",
    "ghostship-victoriametrics": "modules/self-hosted/apparmor/victoriametrics.profile",
    "ghostship-vmalert-logs": "modules/self-hosted/apparmor/vmalert.profile",
    "ghostship-vmalert-metrics": "modules/self-hosted/apparmor/vmalert.profile",
    "ghostship-vmauth": "modules/self-hosted/apparmor/vmauth.profile",
}

# The profile files no policy loads, and why. Every entry needs a reason:
# a file that no policy reads is either a leftover or a policy that this
# host does not load.
UNREFERENCED: dict[str, str] = {
    "tests/fixtures/apparmor/at-transition-limit.profile":
        "a parser fixture for the budget boundary, not a policy the host loads",
    "tests/fixtures/apparmor/too-many-transitions.profile":
        "a parser fixture for the budget boundary, not a policy the host loads",
}

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


class CheckError(Exception):
    """A condition that stops the check before it can report a finding."""


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
    """The profile blocks that name more transitions than the budget allows."""
    return [(name, count) for name, count in named_transitions(text) if count > budget]


def canonical(text: str) -> str:
    """The text the modules may rewrite while rendering a policy.

    The modules drop the complain flag, name the policy after the
    container it runs, and turn the include directives into the store
    paths they resolve to. None of that changes the profile's rules, so
    the check compares the rendered policy with the file it came from
    through these three differences.
    """
    text = text.replace("complain,", "")
    text = re.sub(r"(?m)^([ \t]*)#?include[ \t]+.*$", r"\1#include", text)
    text = re.sub(r"\bghostship-[a-z0-9]+(?:-[a-z0-9]+)*\b", "PROFILE", text)
    return re.sub(r"\s+", " ", text).strip()


def nix_eval_json(root: Path, attribute: str, apply: str | None = None) -> object:
    """The value of a Nix attribute, evaluated in the repository."""
    command = ["nix", "eval", "--no-write-lock-file", "--json", attribute]
    if apply:
        command += ["--apply", apply]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise CheckError(f"{attribute} could not be evaluated: {result.stderr.strip()}")
    return json.loads(result.stdout)


def load_policies(root: Path, host: str) -> dict[str, str]:
    """The profiles the host loads, as the host renders them.

    A policy with the state "disable" is not written to the host's
    /etc/apparmor.d, so the host does not load it and the check does not
    parse it.
    """
    policies = nix_eval_json(
        root, f".#nixosConfigurations.{host}.config.security.apparmor.policies")
    return {name: policy["profile"] for name, policy in sorted(policies.items())
            if policy.get("state") != "disable"}


def realise(root: Path, derivations: list[str]) -> None:
    """Build the derivations the host's include tree is made of."""
    if not derivations:
        return
    result = subprocess.run(
        ["nix", "build", "--no-link", "--no-write-lock-file", *derivations],
        cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise CheckError(
            f"the host's AppArmor include tree could not be built: {result.stderr.strip()}")


def include_paths(root: Path, host: str, scratch: Path) -> list[Path]:
    """The paths the host's parser searches for <tunables/global> and friends.

    The host writes its enabled policies and its include files into
    /etc/apparmor.d, and its parser.conf adds every package in
    security.apparmor.packages to the search path. The check builds the
    same two: the include files the host has, and the packages' own
    directories, which hold the abstractions and the tunables.
    """
    paths: list[Path] = []

    # The host's own include files, named as the host names them.
    includes = nix_eval_json(
        root, f".#nixosConfigurations.{host}.config.security.apparmor.includes",
        apply="incs: builtins.mapAttrs (name: file: file.outPath) incs")
    if includes:
        derive = nix_eval_json(
            root, f".#nixosConfigurations.{host}.config.security.apparmor.includes",
            apply="incs: builtins.mapAttrs (name: file: file.drvPath) incs")
        realise(root, sorted(set(derive.values())))
        directory = scratch / "etc-apparmor.d"
        directory.mkdir(parents=True, exist_ok=True)
        for name, source in includes.items():
            link = directory / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(source)
        paths.append(directory)

    # The packages the host adds to the parser's search path.
    packages = nix_eval_json(
        root, f".#nixosConfigurations.{host}.config.security.apparmor.packages",
        apply="ps: map (p: p.outPath) ps")
    derive = nix_eval_json(
        root, f".#nixosConfigurations.{host}.config.security.apparmor.packages",
        apply="ps: map (p: p.drvPath) ps")
    realise(root, sorted(set(derive)))
    for package in packages:
        directory = Path(package) / "etc/apparmor.d"
        if not directory.is_dir():
            raise CheckError(f"{package} holds no etc/apparmor.d")
        paths.append(directory)

    # The CI shell names the same tree the host uses.
    configured = os.environ.get("APPARMOR_INCLUDE_DIR")
    if configured:
        directory = Path(configured)
        if not directory.is_dir():
            raise CheckError(f"APPARMOR_INCLUDE_DIR={configured} is not a directory")
        paths.append(directory)

    # The same tree twice is one tree.
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def parse_policy(path: Path, includes: list[Path]) -> str:
    """The parser's complaint about a policy, or an empty string."""
    command = ["apparmor_parser", "--skip-kernel-load", "--skip-cache",
               "--config-file", "/dev/null"]
    for directory in includes:
        command += ["-I", str(directory)]
    command.append(str(path))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return ""
    return (result.stdout + result.stderr).strip()


def repository_profiles(root: Path) -> list[str]:
    """The profile files in the repository."""
    profiles = []
    for path in root.rglob("*.profile"):
        relative = path.relative_to(root)
        if ".git" in relative.parts:
            continue
        profiles.append(str(relative))
    return sorted(profiles)


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
            f"{accepted.name} names {count}/{TRANSITION_BUDGET} named transitions in "
            f"{name} and must pass the budget")
    under = budget_violations(refused.read_text())
    if not under:
        failures.append(
            f"{refused.name} names 13 transitions and must fail the "
            f"{TRANSITION_BUDGET} transition budget")
    elif under[0][1] != 13:
        failures.append(
            f"{refused.name} names {under[0][1]} transitions and must name 13")
    return failures


def check_policies(root: Path, host: str, policies: dict[str, str],
                   includes: list[Path]) -> tuple[list[str], list[str]]:
    """Parse and count every policy the host loads.

    Returns the findings and the report lines.
    """
    failures: list[str] = []
    report: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        for name, profile in policies.items():
            path = Path(directory) / name
            path.write_text(profile)
            complaint = parse_policy(path, includes)
            if complaint:
                failures.append(f"the {name} policy does not parse:\n{complaint}")
            counts = named_transitions(profile)
            worst = max(counts, key=lambda entry: entry[1], default=("", 0))
            source = POLICY_SOURCES.get(name, "a policy this repository does not declare")
            if worst[1] >= REPORT_AT:
                report.append(f"  {name}: {worst[1]}/{TRANSITION_BUDGET} named transitions "
                              f"({source})")
            else:
                report.append(f"  {name}: parsed ({source})")
            for block, count in counts:
                if count > TRANSITION_BUDGET:
                    failures.append(
                        f"the {name} policy names {count}/{TRANSITION_BUDGET} named "
                        f"transitions in {block}; apparmor_parser refuses the whole policy")
            if name.startswith("ghostship-") and name not in POLICY_SOURCES:
                failures.append(
                    f"the {name} policy is loaded but this check does not know the file it "
                    f"comes from; add it to POLICY_SOURCES")
            if name in POLICY_SOURCES:
                source_path = root / POLICY_SOURCES[name]
                if not source_path.is_file():
                    failures.append(
                        f"the {name} policy comes from {POLICY_SOURCES[name]}, which does "
                        f"not exist")
                    continue
                if canonical(profile) != canonical(source_path.read_text()):
                    failures.append(
                        f"the {name} policy does not match {POLICY_SOURCES[name]}; the "
                        f"rendering or the file changed")
    return failures, report


def check_coverage(root: Path, host: str, policies: dict[str, str]) -> list[str]:
    """Hold every profile file to a policy or to the allowlist."""
    failures: list[str] = []
    files = repository_profiles(root)
    referenced = {POLICY_SOURCES[name] for name in policies if name in POLICY_SOURCES}
    for name in files:
        if name in referenced or name in UNREFERENCED:
            continue
        failures.append(
            f"{name} is not loaded by any policy {host} loads; add it to POLICY_SOURCES "
            f"or to the allowlist with a reason")
    for name, reason in UNREFERENCED.items():
        if name not in files:
            failures.append(f"the allowlist names {name}, which is not in the repository")
        if name in referenced:
            failures.append(f"the allowlist names {name}, which a policy loads")
        if not reason.strip():
            failures.append(f"the allowlist entry for {name} needs a reason")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-apparmor-profiles", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=HOST, help="the host whose policies are parsed")
    parser.add_argument("--self-test", action="store_true",
                        help="run the fixture self-test only")
    arguments = parser.parse_args(argv)

    failures: list[str] = []
    report: list[str] = []
    try:
        failures.extend(self_test())
        if not arguments.self_test:
            policies = load_policies(ROOT, arguments.host)
            if not policies:
                raise CheckError(f"{arguments.host} loads no AppArmor policy")
            with tempfile.TemporaryDirectory() as scratch:
                includes = include_paths(ROOT, arguments.host, Path(scratch))
                policy_failures, report = check_policies(
                    ROOT, arguments.host, policies, includes)
            failures.extend(policy_failures)
            failures.extend(check_coverage(ROOT, arguments.host, policies))
    except CheckError as error:
        print(f"apparmor profile check: {error}", file=sys.stderr)
        return 1

    if arguments.self_test:
        print("Checking the AppArmor transition budget fixtures")
    else:
        print(f"Parsing the {len(report)} AppArmor policies {arguments.host} loads")
        for line in report:
            print(line)
    for failure in failures:
        print(f"apparmor profile check: {failure}", file=sys.stderr)
    if failures:
        print(f"apparmor profile check: {len(failures)} failure(s)", file=sys.stderr)
        return 1
    print("apparmor profile check: every loaded policy parses and holds the budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
