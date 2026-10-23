"""Keep the administration PAT inside the privileged registration process."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request


def directories(args):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repository):
        raise ValueError("invalid repository")
    state, work, logs = map(Path, (args.state_dir, args.work_dir, args.logs_dir))
    if any(not path.is_absolute() or path == Path("/") for path in (state, work, logs)):
        raise ValueError("invalid runner directories")
    if len({state, work, logs}) != 3:
        raise ValueError("runner directories must be distinct")
    return state, work, logs


def prepare(args):
    state, work, logs = directories(args)
    owner = state.stat()
    if owner.st_uid == 0:
        raise ValueError("runner must have an unprivileged service identity")

    # This process alone reads B. Do not spawn a credentialed curl or shell.
    pat = Path(args.token_file).read_text().strip()
    request = urllib.request.Request(
        f"https://api.github.com/repos/{args.repository}/actions/runners/registration-token",
        data=b"", method="POST", headers={
            "Authorization": "Bearer " + pat,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    with urllib.request.urlopen(request, timeout=30) as response:
        token = json.load(response)["token"]
    if not isinstance(token, str) or not token:
        raise ValueError("missing registration token")

    # Ephemeral runners start with fresh state/work; their cache and logs persist.
    for directory in (state, work):
        for entry in directory.iterdir():
            if entry.is_symlink() or not entry.is_dir():
                entry.unlink()
            else:
                shutil.rmtree(entry)
        (directory / "_diag").symlink_to(logs, target_is_directory=True)
    # DynamicUser state is id-mapped: its host owner may be nobody. Preserve
    # that ownership rather than trying to run a host child as the dynamic UID.
    # This file contains only the one-use registration token, never the PAT.
    fd = os.open(state / ".registration-token", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
        stream.write(token)


def configure(args):
    state, work, _ = directories(args)
    if os.geteuid() == 0 or state.stat().st_uid != os.geteuid():
        raise ValueError("configure must run as the service identity")
    token_file = state / ".registration-token"
    try:
        token = token_file.read_text()
    finally:
        token_file.unlink(missing_ok=True)
    if not token:
        raise ValueError("missing registration token")
    environment = dict(os.environ)
    for key in list(environment):
        if key.upper().startswith("ACTIONS_RUNNER_INPUT_") or key in {"GH_TOKEN", "GITHUB_TOKEN"}:
            del environment[key]
    environment.update(ACTIONS_RUNNER_INPUT_TOKEN=token, RUNNER_ROOT=str(state))
    # Runner.Listener consumes and masks ACTIONS_RUNNER_INPUT_TOKEN. Its argv
    # contains no credential; its later run/job process inherits neither token.
    subprocess.run([
        args.runner, "configure", "--unattended", "--disableupdate",
        "--work", str(work), "--url", f"https://github.com/{args.repository}",
        "--name", args.name, "--labels", args.label, "--ephemeral", "--replace",
    ], env=environment, cwd=state, capture_output=True, check=True, timeout=90)
    for name in (".credentials", ".credentials_rsaparams", ".runner"):
        (work / name).symlink_to(state / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--op", choices=("prepare", "configure"), required=True)
    for name in ("runner", "token-file", "repository", "name", "label",
                 "state-dir", "work-dir", "logs-dir"):
        parser.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args()
        (prepare if args.op == "prepare" else configure)(args)
    except Exception as error:
        # API/runner error bodies can contain credentials. Never replay them.
        print(f"Runner registration failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    print("Runner registration completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
