"""Run the managed agent installer when a generation changes its pinned release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

RELEASE_FIELDS = ("version", "source", "revision", "package")


def release_differs(installed: dict, deployed: dict) -> bool:
    """Whether the deployed generation names a different managed release."""
    return any(installed.get(field) != deployed.get(field) for field in RELEASE_FIELDS)


def read_record(path: Path, *, missing_ok: bool = False) -> dict:
    try:
        record = json.loads(path.read_text())
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise
    if not isinstance(record, dict):
        raise ValueError("release record must be a JSON object")
    return record


def refresh_if_needed(installed_path: Path, deployed_path: Path, command: list[str]) -> bool:
    """Run the supplied refresh command once when installed and deployed differ."""
    installed = read_record(Path(installed_path), missing_ok=True)
    deployed = read_record(Path(deployed_path))
    if not release_differs(installed, deployed):
        return False
    if not command:
        raise ValueError("refresh command is required when releases differ")
    subprocess.run(command, check=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--deployed", type=Path, required=True)
    parser.add_argument("--refresh-command", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args(argv)
    command = args.refresh_command
    if command and command[0] == "--":
        command = command[1:]
    try:
        refresh_if_needed(args.installed, args.deployed, command)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"managed agent release refresh failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
