"""Publish a copied runtime atomically; only its own changed code needs restart."""
import argparse
import os
from pathlib import Path
import subprocess


def publish(state, runtime):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    current = state / "current"
    if current.is_symlink() and os.readlink(current) == runtime:
        return False
    temporary = state / "current.new"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(runtime)
    temporary.replace(current)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--systemctl", required=True)
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()
    # Store copying and GC-root publication must succeed before reaching here.
    publish(args.state, args.runtime)
    acknowledged = Path(args.state) / "restart-requested"
    if args.no_restart:
        return
    if not acknowledged.is_symlink() or os.readlink(acknowledged) != args.runtime:
        active = subprocess.run([args.systemctl, "is-active", "--quiet", args.unit], check=False)
        if active.returncode == 0:
            subprocess.run([args.systemctl, "--no-block", "try-restart", args.unit], check=True)
        # A rejected restart must remain retryable even though current is
        # already published. Inactive services load current on their next start.
        temporary = Path(args.state) / "restart-requested.new"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(args.runtime)
        temporary.replace(acknowledged)


if __name__ == "__main__":
    main()
