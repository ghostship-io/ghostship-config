#!/usr/bin/env python3
"""Guard the agent pin against a regression.

A pull request that moves the `ghostship-private-agent` pin to a revision that
does not descend from the pinned one silently drops everything that is on the
pinned line. The check fails unless the new revision descends from the old
one, the pull request body or one of its commits carries an explicit
`pin-regression-approved:` line that names the reason, or the repository owner
has approved the pull request (an owner APPROVE review, or an owner comment).
An owner override is standing authority for that pull request; it does not
weaken the downgrade protection, because the ancestry question is still asked
and "cannot compare" is still a refusal.

The check reads the two flake locks and the pull request metadata, and asks
git whether the new revision descends from the pinned one. It never writes to
the agent repository.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import private_source  # noqa: E402

INPUT = "ghostship-private-agent"
APPROVAL = re.compile(r"^\s*pin-regression-approved:\s*(\S.*)$", re.MULTILINE)


def pinned_revision(lock: dict) -> str | None:
    """The revision a flake lock pins for the agent input."""
    return lock.get("nodes", {}).get(INPUT, {}).get("locked", {}).get("rev")


def approval_reason(text: str) -> str | None:
    """The reason of an explicit approval line, when the text carries one."""
    match = APPROVAL.search(text or "")
    return match.group(1).strip() if match else None


def ancestry(repository: Path, old: str, new: str) -> bool | None:
    """True when the new revision descends from the old one.

    None means the question could not be answered, which is not the same as a
    revision that does not descend.
    """
    result = subprocess.run(["git", "-C", str(repository), "merge-base", "--is-ancestor", old, new],
                            capture_output=True, text=True)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def owner_logins() -> set[str]:
    """The repository owner's GitHub login(s), from the deployment environment."""
    raw = os.environ.get("GHOSTSHIP_OWNER_LOGINS", "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


def api(path: str) -> list:
    """Read a GitHub API list, or nothing when it cannot be read."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_META_TOKEN") or ""
    if not token:
        return []
    request = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "check-agent-pin"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return []
    return value if isinstance(value, list) else []


def owner_approval(payload: dict) -> str | None:
    """An owner APPROVE review or owner comment on the pull request, if any.

    The request is not fetched when no owner login is configured, so the guard
    keeps working offline and in tests without credentials.
    """
    logins = owner_logins()
    if not logins:
        return None
    pull_request = payload.get("pull_request") or {}
    repository = payload.get("repository") or {}
    number = pull_request.get("number")
    full_name = repository.get("full_name")
    if not number or not full_name:
        return None
    for review in api(f"/repos/{full_name}/pulls/{number}/reviews"):
        login = (review.get("user") or {}).get("login", "")
        if review.get("state") == "APPROVED" and login.lower() in logins:
            return f"APPROVE review by {login}"
    for comment in api(f"/repos/{full_name}/issues/{number}/comments"):
        login = (comment.get("user") or {}).get("login", "")
        if login.lower() in logins:
            return f"comment by {login}"
    return None


def evaluate(base_rev: str | None, head_rev: str | None, approved: str | None,
             repository: Path | None, owner: str | None = None) -> tuple[bool, str]:
    """Decide whether the pin move is acceptable."""
    if not base_rev or not head_rev:
        return True, "the agent input is not pinned in both revisions"
    if base_rev == head_rev:
        return True, f"the agent pin is unchanged at {head_rev}"
    if approved:
        return True, f"the pin move to {head_rev} is approved: {approved}"
    if owner:
        return True, f"the pin move to {head_rev} is approved by the owner: {owner}"
    if repository is None:
        return False, (f"the agent pin moves from {base_rev} to {head_rev}, and the agent source "
                       "for the pinned revision is unavailable, so the move cannot be shown to "
                       "descend from it. Add a `pin-regression-approved: <reason>` line to the pull "
                       "request body or to a commit.")
    relation = ancestry(repository, base_rev, head_rev)
    if relation is None:
        return False, (f"the agent pin moves from {base_rev} to {head_rev}, and the two revisions "
                       "could not be compared. Add a `pin-regression-approved: <reason>` line to the "
                       "pull request body or to a commit.")
    if relation:
        return True, f"the agent pin moves to {head_rev}, which descends from {base_rev}"
    return False, (f"the agent pin moves from {base_rev} to {head_rev}, which does not descend from "
                   "the pinned revision and would drop everything on the pinned line. Add a "
                   "`pin-regression-approved: <reason>` line to the pull request body or to a commit.")


def read_lock(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise SystemExit(f"check-agent-pin: cannot read {path}: {error}")


def git_output(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout


def event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def prepare_repository(base_lock: dict, head_lock: dict, base_rev: str, head_rev: str,
                       working_lock: dict | None = None) -> tuple[Path | None, Path | None]:
    """A repository that holds both revisions, and the directory to remove after.

    The CI import leaves a shallow copy of the pinned revision behind, which
    does not hold the base revision. The read-only key fetches both revisions
    with their history, so that git can answer the ancestry question.
    """
    for lock in (head_lock, working_lock or {}):
        imported = private_source.local_repository(lock, INPUT)
        if imported is not None and private_source.has_revision(imported, base_rev) \
                and private_source.has_revision(imported, head_rev):
            return imported, None
    imported = private_source.local_repository(head_lock, INPUT)
    key = os.environ.get("GHOSTSHIP_AGENT_READ_KEY", "")
    url = private_source.git_ssh_url(base_lock, INPUT)
    if not key or not url:
        return imported, None
    root = Path(tempfile.mkdtemp(prefix="ghostship-agent-pin-"))
    key_path = root / "agent.key"
    try:
        key_path.write_text(key + "\n")
        key_path.chmod(0o600)
        hosts = private_source.known_hosts(
            root / "known_hosts",
            private_source.github_host_keys(os.environ.get("GITHUB_META_TOKEN", "")))
        environment = private_source.ssh_environment(key_path, hosts)
        private_source.fetch_revisions(root / "agent", url, [base_rev, head_rev], environment)
    except (OSError, subprocess.SubprocessError, ValueError):
        shutil.rmtree(root, ignore_errors=True)
        return imported, None
    finally:
        key_path.unlink(missing_ok=True)
    return root / "agent", root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-agent-pin", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-lock", help="the base branch's flake.lock")
    parser.add_argument("--head-lock", help="the pull request's flake.lock")
    parser.add_argument("--approvals", help="a file whose text carries the approval line")
    parser.add_argument("--agent-repo", help="a git repository holding the agent revisions")
    arguments = parser.parse_args(argv)

    payload = event()
    pull_request = payload.get("pull_request")
    texts: list[str] = []
    if arguments.base_lock and arguments.head_lock:
        base_lock = read_lock(arguments.base_lock)
        head_lock = read_lock(arguments.head_lock)
    elif pull_request:
        base_sha = pull_request["base"]["sha"]
        head_sha = pull_request["head"]["sha"]
        base_text = git_output("show", f"{base_sha}:flake.lock")
        head_text = git_output("show", f"{head_sha}:flake.lock")
        if not base_text or not head_text:
            print("check-agent-pin: the pull request's flake locks are not available, skipping")
            return 0
        base_lock = json.loads(base_text)
        head_lock = json.loads(head_text)
        texts = [pull_request.get("body") or "",
                 git_output("log", "--format=%B", f"{base_sha}..{head_sha}")]
    else:
        print("check-agent-pin: no pull request to check, skipping")
        return 0

    if arguments.approvals:
        texts.append(Path(arguments.approvals).read_text())
    approved = approval_reason("\n".join(text for text in texts if text))
    owner = owner_approval(payload)

    base_rev = pinned_revision(base_lock)
    head_rev = pinned_revision(head_lock)
    cleanup = None
    repository = Path(arguments.agent_repo) if arguments.agent_repo else None
    if repository is None and base_rev and head_rev and base_rev != head_rev:
        working_lock = {}
        if Path("flake.lock").is_file():
            try:
                working_lock = json.loads(Path("flake.lock").read_text())
            except (OSError, ValueError):
                working_lock = {}
        repository, cleanup = prepare_repository(base_lock, head_lock, base_rev, head_rev, working_lock)

    try:
        accepted, message = evaluate(base_rev, head_rev, approved, repository, owner)
    finally:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)
    print(f"check-agent-pin: {message}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
