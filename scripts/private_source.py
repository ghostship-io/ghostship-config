"""Shared access to the private flake sources.

The CI job reaches the private agent repository with a repository-specific
read-only deploy key. The key is written to a temporary file for the fetch
and removed immediately afterwards; it is never kept in the repository or
printed.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

# How much history a fetch keeps, so that an ancestry question between two
# revisions can be answered from the fetched commits alone.
FETCH_DEPTH = 1000

# The owner of the private flake inputs. The organisation owns them now, and
# the previous account is accepted only while a lock still names it: a lock
# written before the transfer keeps working, and nothing else is accepted.
CANONICAL_OWNER = "ghostship-io"
TRANSITION_OWNERS = frozenset({"owner"})
ACCEPTED_OWNERS = frozenset({CANONICAL_OWNER}) | TRANSITION_OWNERS


def accepted_owner(owner: str) -> bool:
    """True when a locked input's owner is one this deployment accepts."""
    return owner in ACCEPTED_OWNERS


def supported_source(locked: dict, repository: str) -> bool:
    """True when a locked input is the private source this deployment expects."""
    return (locked.get("type") == "github"
            and accepted_owner(locked.get("owner") or "")
            and locked.get("repo") == repository)


def github_host_keys(token: str = "") -> list[str]:
    """The SSH host keys GitHub publishes, so a fetch can verify the host."""
    headers = {"User-Agent": "ghostship-private-inputs"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("https://api.github.com/meta", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["ssh_keys"]


def known_hosts(path: Path, keys: list[str]) -> Path:
    """A known_hosts file for github.com."""
    path.write_text("".join(f"github.com {key}\n" for key in keys))
    return path


def ssh_environment(key_path: Path, known_hosts_path: Path) -> dict:
    """An environment that uses one read-only key for git over SSH."""
    env = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    env["GIT_SSH_COMMAND"] = ("ssh -i " + str(key_path) + " -o IdentitiesOnly=yes -o BatchMode=yes"
                              + " -o StrictHostKeyChecking=yes -o UserKnownHostsFile=" + str(known_hosts_path))
    return env


def git_ssh_url(lock: dict, name: str) -> str | None:
    """The SSH URL of a locked GitHub flake input."""
    node = lock.get("nodes", {}).get(name, {}).get("locked", {})
    if node.get("type") != "github":
        return None
    owner, repository = node.get("owner"), node.get("repo")
    if not owner or not repository:
        return None
    return f"git@github.com:{owner}/{repository}.git"


def local_repository(lock: dict, name: str) -> Path | None:
    """The local repository a CI import left behind for a locked input."""
    node = lock.get("nodes", {}).get(name, {}).get("locked", {})
    if node.get("type") != "git":
        return None
    url = node.get("url", "")
    if not url.startswith("file://"):
        return None
    return Path(url[len("file://"):])


def fetch_source(repository: Path, url: str, revision: str, env: dict) -> None:
    """Fetch one revision, with its files, into a repository."""
    repository.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repository)], env=env, check=True)
    subprocess.run(["git", "-C", str(repository), "fetch", "-q", "--depth=1", url, revision],
                   env=env, check=True)
    subprocess.run(["git", "-C", str(repository), "checkout", "-q", "--detach", "FETCH_HEAD"],
                   env=env, check=True)


def fetch_revisions(repository: Path, url: str, revisions: list[str], env: dict) -> None:
    """Fetch revisions, with their history but without their files.

    The ancestry question only needs the commits, so the files stay out of the
    fetch and it stays cheap.
    """
    repository.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repository)], env=env, check=True)
    subprocess.run(["git", "-C", str(repository), "fetch", "-q", "--filter=blob:none",
                    f"--depth={FETCH_DEPTH}", url, *revisions], env=env, check=True)


def has_revision(repository: Path, revision: str) -> bool:
    """True when the repository already holds the revision."""
    result = subprocess.run(["git", "-C", str(repository), "cat-file", "-e", f"{revision}^{{commit}}"],
                            capture_output=True, text=True)
    return result.returncode == 0
