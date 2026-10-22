"""Compare the running system with the system profile.

An activation must record the system generation. After a switch,
/run/current-system and /nix/var/nix/profiles/system name the same store
path. When they differ, the profile does not describe the running system and
a reboot would revert the activation, so a mismatch that lasts longer than
the threshold reaches operations through ghostship-notify with a stable
dedupe key. The check only reads two symlinks; it never searches the host.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEDUPE_KEY = "boot-generation-drift"


def read_generation(path: str) -> str | None:
    """The store path a generation link resolves to, or None when it is absent."""
    if not os.path.exists(path):
        return None
    try:
        return os.path.realpath(path)
    except OSError:
        return None


def drifted(current: str | None, profile: str | None) -> bool:
    """True when the running system and the system profile disagree."""
    if current is None or profile is None:
        return False
    return current != profile


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


def notify(config: dict, status: str, message: str) -> bool:
    """Publish the drift through the host notifier."""
    command = [
        config["notify"],
        "--topic", "operations",
        "--priority", "4" if status == "firing" else "2",
        "--source", "boot-generation",
        "--state", status,
        "--dedupe", DEDUPE_KEY,
        "--title", f"Boot generation drift {status} on {os.uname().nodename}",
        message,
    ]
    try:
        return subprocess.run(command, check=False, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostship-boot-generation-drift", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    state_path = Path(config["state"])
    state = load_state(state_path)
    current = read_generation(config["current"])
    profile = read_generation(config["profile"])
    now = float(os.environ.get("GHOSTSHIP_DRIFT_NOW") or time.time())
    threshold = float(config.get("threshold", 600))

    if not drifted(current, profile):
        if state.get("firing"):
            notify(config, "resolved",
                   "The running system and the system profile name the same generation again.")
        save_state(state_path, {})
        print(f"boot generation: in sync ({current})")
        return 0

    first_seen = float(state.get("first_seen") or now)
    state = {"first_seen": first_seen, "current": current, "profile": profile}
    if now - first_seen < threshold:
        save_state(state_path, state)
        print(f"boot generation: drift observed for {int(now - first_seen)}s, waiting for the threshold")
        return 0
    state["firing"] = True
    save_state(state_path, state)
    notify(config, "firing",
           f"The running system {current} and the system profile {profile} differ. "
           "A reboot would revert to the profile's generation. Set the system profile "
           "before switching, and verify that the two match.")
    print(f"boot generation: drift reported ({current} != {profile})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
