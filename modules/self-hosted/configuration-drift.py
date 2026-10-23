"""Report a running NixOS configuration that drifts from the source branch.

The running revision comes from the running system itself:
`/run/current-system/sw/bin/nixos-version --configuration-revision`, which the
module records through `system.configurationRevision = self.rev`. The source
checkout and the evaluated candidate are never read for that value.

The check is read-only against the host. It reads the running system and the
system profile, asks the running system for its revision, and fetches the
source repository only into its own private state directory. It never builds,
switches, sets the system profile, activates a generation, stops a timer or
restarts a service.

A running revision that is behind main is reported once it has stayed behind
for longer than the threshold, measured from the first observation of that
same revision. Main advancing does not restart the observation; convergence or
a new running revision clears it. A running system that does not match the
system profile is reported immediately, because a reboot would revert the
activation. Fetch failures, missing or dirty running revisions, unrelated
histories and missing symlinks are explicit errors, never a healthy result,
and a failed notification reaches the caller as a nonzero result so the next
execution retries it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEDUPE_GENERATION = "configuration-drift-generation"
DEDUPE_REVISION = "configuration-drift-revision"
REVISION = re.compile(r"[0-9a-f]{7,64}")
DEFAULT_THRESHOLD = 86400


def note(message: str) -> None:
    print(f"configuration-drift: {message}")


def error(message: str) -> None:
    print(f"configuration-drift: {message}", file=sys.stderr)


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def read_link(path: str) -> str | None:
    """The store path a running-system or profile link names, when it exists."""
    if not os.path.isdir(path):
        return None
    try:
        return os.path.realpath(path)
    except OSError:
        return None


def running_revision(running_system: str) -> tuple[str | None, str | None]:
    """The configuration revision the running system recorded, or an error."""
    tool = Path(running_system) / "sw/bin/nixos-version"
    if not tool.is_file():
        return None, f"the running system has no {tool}"
    try:
        result = subprocess.run(
            [str(tool), "--configuration-revision"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exception:
        return None, f"cannot read the running configuration revision: {exception}"
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return None, f"the running configuration revision is unknown: {detail}"
    value = result.stdout.strip()
    if not REVISION.fullmatch(value):
        return None, (
            "the running configuration revision is unknown "
            f"({value or 'empty'}); a dirty or missing revision is never healthy"
        )
    return value, None


def git_environment(state: Path) -> dict[str, str]:
    """Run git without the host's or the caller's configuration."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        }
    }
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "HOME": str(state),
            "XDG_CACHE_HOME": str(state),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def git(config: dict, cache: Path, *arguments: str) -> subprocess.CompletedProcess:
    command = [config.get("git") or "git", "--git-dir", str(cache), *arguments]
    return subprocess.run(
        command,
        cwd=config["state"],
        env=git_environment(Path(config["state"])),
        capture_output=True,
        text=True,
        timeout=300,
    )


def ensure_cache(config: dict, cache: Path) -> str | None:
    """Create the private bare cache, never a checkout, or return an error."""
    if (cache / "HEAD").is_file():
        return None
    cache.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [config.get("git") or "git", "init", "--bare", "--quiet", str(cache)],
            cwd=config["state"],
            env=git_environment(Path(config["state"])),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exception:
        return f"cannot create the private git cache: {exception}"
    if result.returncode != 0:
        return f"cannot create the private git cache: {result.stderr.strip()}"
    return None


def fetch_main(config: dict) -> tuple[dict[str, str] | None, str | None]:
    """Fetch the branch into the private cache and resolve its tip."""
    branch = config.get("branch") or "main"
    cache = Path(config["state"]) / "repository.git"
    problem = ensure_cache(config, cache)
    if problem is not None:
        return None, problem
    try:
        fetched = git(
            config,
            cache,
            "fetch",
            "--quiet",
            "--no-tags",
            "--prune",
            config["remote"],
            f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
        )
    except (OSError, subprocess.SubprocessError) as exception:
        return None, f"fetch of {config['remote']} failed: {exception}"
    if fetched.returncode != 0:
        detail = fetched.stderr.strip() or f"exit {fetched.returncode}"
        return None, f"fetch of {config['remote']} failed: {detail}"
    tip = git(config, cache, "rev-parse", "--verify", f"refs/remotes/origin/{branch}")
    if tip.returncode != 0 or not tip.stdout.strip():
        detail = tip.stderr.strip() or f"exit {tip.returncode}"
        return None, f"the fetched {branch} tip cannot be resolved: {detail}"
    return {"cache": str(cache), "main": tip.stdout.strip()}, None


def common_ancestor(config: dict, source: dict, running: str) -> tuple[str | None, str | None]:
    """The merge base of the running revision and main, or an explicit error."""
    cache = Path(source["cache"])
    present = git(config, cache, "cat-file", "-e", f"{running}^{{commit}}")
    if present.returncode != 0:
        return None, (
            f"the running revision {running} is not in the fetched history of "
            f"{config['remote']}; the host may not have been built from this repository"
        )
    merged = git(config, cache, "merge-base", running, source["main"])
    if merged.returncode == 0 and merged.stdout.strip():
        return merged.stdout.strip(), None
    if merged.returncode == 1 and not merged.stdout.strip():
        return None, (
            f"the running revision {running} and {config['remote']} have unrelated histories"
        )
    detail = merged.stderr.strip() or f"exit {merged.returncode}"
    return None, f"cannot compare the running revision with {config['remote']}: {detail}"


def notify(config: dict, dedupe: str, title: str, message: str) -> bool:
    """Publish one security notification without asking for an incident thread."""
    command = [
        config["notify"],
        "--topic",
        "security",
        "--priority",
        "4",
        "--source",
        "configuration",
        "--state",
        "firing",
        "--dedupe",
        dedupe,
        "--title",
        title,
        message,
    ]
    try:
        return subprocess.run(command, check=False, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghostship-configuration-drift",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    state_path = Path(config["state"]) / "state.json"
    threshold = float(config.get("threshold", DEFAULT_THRESHOLD))
    now = float(os.environ.get("GHOSTSHIP_CONFIGURATION_DRIFT_NOW") or time.time())
    host = os.uname().nodename
    delivered = True

    # A generation mismatch is reported immediately, without waiting for the
    # revision threshold and without a successful fetch: a reboot would revert
    # the activation, whatever the revision age.
    running_system = read_link(config["running_system"])
    profile = read_link(config["profile"])
    if running_system is None:
        error(f"the running system link {config['running_system']} is missing")
        return 1
    if profile is None:
        error(f"the system profile link {config['profile']} is missing")
        return 1
    if running_system != profile:
        message = (
            f"The running system {running_system} and the system profile {profile} "
            "differ. A reboot would revert to the profile's generation. Set the "
            "system profile before switching, and verify that the two match."
        )
        if notify(config, DEDUPE_GENERATION, f"Configuration generation drift on {host}", message):
            note(f"generation drift reported ({running_system} != {profile})")
        else:
            error("the generation drift notification could not be delivered")
            delivered = False
    else:
        note(f"generation: the running system names the profile ({running_system})")

    running, problem = running_revision(config["running_system"])
    if problem is not None:
        error(problem)
        return 1

    source, problem = fetch_main(config)
    if problem is not None:
        error(problem)
        return 1

    ancestor, problem = common_ancestor(config, source, running)
    if problem is not None:
        error(problem)
        return 1

    state = load_state(state_path)
    main = source["main"]
    if running == main:
        if state:
            save_state(state_path, {})
        note(f"revision: up to date with {main}")
        return 0 if delivered else 1

    if ancestor == main:
        # The running revision contains main: it is ahead, never behind.
        if state:
            save_state(state_path, {})
        note(f"revision: {running} is ahead of {main}")
        return 0 if delivered else 1

    if ancestor != running:
        error(
            f"the running revision {running} has diverged from {main} "
            f"(common ancestor {ancestor}); refusing to call it behind"
        )
        return 1

    first = state.get("first_observed_behind")
    if state.get("running_revision") != running or not isinstance(first, (int, float)):
        first = now
    first = float(first)
    # Main advancing keeps the first observation of this running revision.
    state = {
        "running_revision": running,
        "first_observed_behind": first,
        "main_revision": main,
    }
    save_state(state_path, state)

    age = now - first
    if age <= threshold:
        note(
            f"revision: {running} is behind {main} for {int(age)}s; "
            f"the {int(threshold)}s threshold has not passed"
        )
        return 0 if delivered else 1

    message = (
        f"The running configuration revision {running} has been behind main {main} "
        f"for {int(age)}s (first observed {int(first)}). The threshold is "
        f"{int(threshold)}s. Nothing was built, switched or activated; update the "
        "host through change control."
    )
    if notify(config, DEDUPE_REVISION, f"Configuration revision drift on {host}", message):
        note(f"revision drift reported ({running} is behind {main} for {int(age)}s)")
    else:
        error("the revision drift notification could not be delivered")
        delivered = False
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
