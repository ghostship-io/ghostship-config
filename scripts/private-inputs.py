#!/usr/bin/env python3
"""Supply the private flake source to flake.nix and flake.lock.

The public repository names no private repository, revision, or content hash.
The committed tree carries a resolvable placeholder, and the pinned source is
supplied from a private specification:

* continuous integration reads it from a repository secret, and
* a deployment host reads it from a root-only file outside the checkout.

The importer copies the pinned source into the Nix store before it cleans up.
The lock then names the store path, so the evaluation still resolves after the
importer has exited and its working directory is gone.

Nothing this script prints contains a repository name, a revision, or a
content hash. A failure is reported as a step, never as the command that
failed, because the command carries those coordinates.

Usage:
  private-inputs.py apply  --spec <file>   rewrite the tree to the real source
  private-inputs.py import --spec <file>   additionally import the source
                                            through a read-only deploy key and
                                            point the lock at the store
  private-inputs.py restore                restore the committed placeholders
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# These scripts are also loaded directly by tests, outside the CLI's script
# directory. Resolve the shared policy from this trusted source directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_privacy import (
    INPUT, LOCKED_PLACEHOLDER, ORIGINAL_PLACEHOLDER, PLACEHOLDER_PATH,
    PLACEHOLDER_URL, PolicyError, validate_lock,
)


class StepError(Exception):
    """A step failed. The message names the step, never the coordinates."""


def run_checked(arguments, step, environment=None):
    """Run a command, reporting only the step on failure."""
    result = subprocess.run(
        arguments, capture_output=True, check=False, env=environment
    )
    if result.returncode != 0:
        raise StepError(step)
    return result


def load_spec(args):
    if args.spec:
        return json.loads(Path(args.spec).read_text())
    raw = os.environ.get(args.env)
    if not raw:
        raise StepError(
            "the private source specification is missing: pass --spec or set "
            + args.env
        )
    try:
        return json.loads(raw)
    except ValueError:
        raise StepError("the private source specification is not valid JSON") from None


def spec_entry(spec):
    if INPUT not in spec:
        raise StepError("the private source specification has no " + INPUT + " entry")
    entry = spec[INPUT]
    for field in ("owner", "repo", "rev", "narHash"):
        if not entry.get(field):
            raise StepError(
                "the private source specification is missing the " + field + " field")
    return entry


def committed(path):
    result = subprocess.run(
        ["git", "show", "HEAD:" + path], capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def require_committed_placeholder():
    """The published tree must carry the placeholder, not a real source.

    Without this the specification could be smuggled into the repository as a
    structured document, because the guard that protects the committed tree
    would be looking at a tree that already contains the answer.
    """
    flake = committed("flake.nix")
    if flake is None:
        raise StepError("flake.nix is not committed")
    if PLACEHOLDER_URL not in flake:
        raise StepError(
            "the committed flake.nix does not carry the private source "
            "placeholder; the published tree must not name a private source")
    lock = committed("flake.lock")
    if lock is None:
        raise StepError("flake.lock is not committed")
    try:
        validate_lock(lock)
    except PolicyError:
        raise StepError("the committed flake.lock violates the public source policy") from None


def read_tree():
    flake_nix = Path("flake.nix")
    lock_path = Path("flake.lock")
    if not flake_nix.is_file() or not lock_path.is_file():
        raise StepError("run this from the repository root")
    return flake_nix, lock_path, json.loads(lock_path.read_text())


def apply_source(entry):
    """Write the real source into flake.nix and flake.lock."""
    flake_nix, lock_path, lock = read_tree()
    url = "github:{owner}/{repo}/{rev}".format(**entry)
    text = flake_nix.read_text()
    marker = 'ghostship-private-agent.url = "{0}";'.format(PLACEHOLDER_URL)
    if marker not in text:
        raise StepError("flake.nix does not carry the expected placeholder")
    flake_nix.write_text(
        text.replace(marker, 'ghostship-private-agent.url = "{0}";'.format(url), 1))

    locked = {
        "lastModified": entry.get("lastModified", 0),
        "narHash": entry["narHash"],
        "owner": entry["owner"],
        "repo": entry["repo"],
        "rev": entry["rev"],
        "type": "github",
    }
    original = {
        "owner": entry["owner"],
        "repo": entry["repo"],
        "rev": entry["rev"],
        "type": "github",
    }
    node = lock["nodes"].setdefault(INPUT, {})
    node["locked"] = locked
    node["original"] = original
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    return locked


def restore_placeholders():
    """Put the committed placeholders back."""
    flake_nix, lock_path, lock = read_tree()
    text = flake_nix.read_text()
    marker = 'ghostship-private-agent.url = "{0}";'.format(PLACEHOLDER_URL)
    line = 'ghostship-private-agent.url = "github:{owner}/{repo}/{rev}";'
    for entry in owner_repo_rev():
        text = text.replace(
            line.format(owner=entry[0], repo=entry[1], rev=entry[2]), marker
        )
    if marker not in text:
        raise StepError("flake.nix does not carry the expected placeholder")
    flake_nix.write_text(text)
    node = lock["nodes"].setdefault(INPUT, {})
    node["locked"] = dict(LOCKED_PLACEHOLDER)
    node["original"] = dict(ORIGINAL_PLACEHOLDER)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")


def owner_repo_rev():
    """Every owner, repository, and revision currently written into flake.nix."""
    text = Path("flake.nix").read_text()
    marker = 'ghostship-private-agent.url = "github:'
    found = []
    for line in text.splitlines():
        if marker in line:
            value = line.split(marker, 1)[1].split('"', 1)[0]
            parts = value.split("/")
            if len(parts) == 3:
                found.append(tuple(parts))
    return found


def import_source(entry, root):
    """Fetch the private source, verify it, and copy it into the store.

    The store copy is what the lock names, so the evaluation still resolves
    after this function returns and the working directory is removed.
    """
    source = fetch_source(entry, root)
    return import_into_store(source, entry)


def import_into_store(source, entry):
    """Verify the content hash and copy the source into the Nix store.

    The store copy is durable. It survives the removal of the working
    directory, so the evaluation that follows the importer still resolves.
    """
    actual = run_checked(
        ["nix", "hash", "path", str(source)], "hashing the private source"
    ).stdout.decode("utf-8", errors="replace").strip()
    if actual != entry["narHash"]:
        raise StepError("the pinned private source does not match its content hash")
    store_path = run_checked(
        ["nix", "store", "add-path", "--name", "private-source", str(source)],
        "copying the private source into the Nix store",
    ).stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
    if not store_path.startswith("/nix/store/"):
        raise StepError("the private source was not copied into the Nix store")
    return store_path


def fetch_source(entry, root):
    """Fetch the pinned source with the scoped read-only deploy key."""
    credential = os.environ.get("GHOSTSHIP_AGENT_READ_KEY", "").strip()
    if not credential:
        raise StepError("the scoped read-only deploy key for the private source is missing")
    key_path = root / "agent.key"
    key_path.write_text(credential + "\n")
    key_path.chmod(0o600)
    known = root / "known_hosts"
    headers = {"User-Agent": "ghostship-private-inputs"}
    token = os.environ.pop("GITHUB_META_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request("https://api.github.com/meta", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            host_keys = json.load(response)["ssh_keys"]
    except Exception:
        raise StepError("the forge host keys could not be read") from None
    known.write_text("".join("github.com " + key + "\n" for key in host_keys))
    checkout = root / "checkout"
    environment = {name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ}
    environment["GIT_SSH_COMMAND"] = (
        "ssh -i " + str(key_path)
        + " -o IdentitiesOnly=yes -o BatchMode=yes"
        + " -o StrictHostKeyChecking=yes -o UserKnownHostsFile=" + str(known)
    )
    try:
        run_checked(["git", "init", "-q", str(checkout)], "initialising the checkout", environment)
        run_checked(
            ["git", "-C", str(checkout), "fetch", "-q", "--depth=1",
             "git@github.com:{0}/{1}.git".format(entry["owner"], entry["repo"]), entry["rev"]],
            "fetching the pinned private source", environment)
        run_checked(
            ["git", "-C", str(checkout), "checkout", "-q", "--detach", "FETCH_HEAD"],
            "checking out the pinned private source", environment)
        archive = root / "source.tar"
        archived = run_checked(
            ["git", "-C", str(checkout), "archive", "FETCH_HEAD"],
            "archiving the pinned private source", environment)
        archive.write_bytes(archived.stdout)
        source = root / "source"
        source.mkdir()
        with tarfile.open(archive) as packed:
            packed.extractall(source, filter="data")
        return source
    finally:
        key_path.unlink(missing_ok=True)
        known.unlink(missing_ok=True)
        shutil.rmtree(checkout, ignore_errors=True)


def point_lock_at_store(lock_path, store_path, entry):
    lock = json.loads(lock_path.read_text())
    node = lock["nodes"].setdefault(INPUT, {})
    node["locked"] = {
        "type": "path",
        "path": store_path,
        "narHash": entry["narHash"],
        "lastModified": entry.get("lastModified", 0),
    }
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["apply", "import", "restore"])
    parser.add_argument("--spec", help="path to the private source specification")
    parser.add_argument("--env", default="GHOSTSHIP_PRIVATE_SOURCES",
                        help="environment variable holding the specification")
    args = parser.parse_args()

    try:
        if args.operation == "restore":
            restore_placeholders()
            print("Restored the committed private source placeholders")
            return 0

        require_committed_placeholder()
        entry = spec_entry(load_spec(args))
        apply_source(entry)
        if args.operation == "import":
            root = Path(tempfile.mkdtemp(prefix="ghostship-private-source-"))
            try:
                store_path = import_source(entry, root)
                point_lock_at_store(Path("flake.lock"), store_path, entry)
            finally:
                shutil.rmtree(root, ignore_errors=True)
    except StepError as error:
        print("Private source step failed: {0}".format(error), file=sys.stderr)
        return 1
    print("Applied the private source specification for " + INPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
