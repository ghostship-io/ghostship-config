#!/usr/bin/env python3
"""Read-only in-candidate isolation observer for candidate rehearsal."""

import json
import os
from pathlib import Path
import subprocess
import sys


AUTH_PATHS = (
    ".local/share/opencode/auth.json",
    ".config/opencode/auth.json",
    ".codex/auth.json",
    ".config/opencode-free/config/auth.json",
    ".config/opencode-free/data/auth.json",
)
AUTH_NAMES = {
    "OPENCODE_AUTH_CONTENT", "LITEROUTER_API_KEY", "OPENCODE_API_KEY",
    "OPENROUTER_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY",
    "GROQ_API_KEY", "COMMAND_CODE_API_KEY", "OLLAMA_API_KEY", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
}


def _names(path):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    return sorted({line.split(b"=", 1)[0].decode("utf-8", "replace")
                   for line in raw.split(b"\0") if b"=" in line})


def _main_pid():
    """The T3 server PID, or None when systemd cannot name it."""
    try:
        result = subprocess.run(
            ["systemctl", "show", "t3code-server.service", "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pid = result.stdout.strip()
    if result.returncode == 0 and pid.isdigit() and pid != "0":
        return pid
    return None


def _pids():
    found = []
    main = _main_pid()
    if main:
        found.append(main)
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or entry.name in found:
            continue
        try:
            comm = (entry / "comm").read_text().strip().lower()
        except OSError:
            continue
        if any(token in comm for token in ("t3", "opencode", "node", "bun")):
            found.append(entry.name)
    return found


def main():
    home = Path(os.environ.get("HOME", "/home/t3code"))
    auth = {name: (home / name).exists() for name in AUTH_PATHS}
    pids = _pids()
    env_names = {}
    for pid in pids:
        names = _names(f"/proc/{pid}/environ")
        if names is not None:
            env_names[pid] = names
    settings_path = home / ".t3/userdata/settings.json"
    instances = {}
    settings_ok = False
    try:
        settings = json.loads(settings_path.read_text())
        settings_ok = True
        for name, instance in (settings.get("providerInstances") or {}).items():
            if isinstance(instance, dict):
                instances[name] = sorted(
                    item.get("name") for item in instance.get("environment") or []
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                )
    except (OSError, ValueError):
        instances = {}
    config_path = home / ".config/opencode-free/config/opencode/opencode.jsonc"
    providers = []
    try:
        config = json.loads(config_path.read_text())
        providers = sorted((config.get("provider") or {}).keys())
    except (OSError, ValueError):
        providers = []
    mounts = []
    mount_violations = []
    try:
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            fields = line.split()
            if len(fields) < 10:
                continue
            target, source = fields[4], fields[9]
            mounts.append({"target": target, "source": source})
            if source.startswith("/srv/apps/t3code/home") or target.startswith("/srv/apps/t3code/home"):
                mount_violations.append(f"production home is mounted at {target}")
            if (target.startswith("/run/secrets/")
                    and target not in ("/run/secrets/t3code.env",)):
                mount_violations.append(f"unexpected secret mount at {target}")
            if "auth.json" in source or "auth.json" in target:
                mount_violations.append(f"host auth path is mounted at {target}")
    except OSError:
        mounts = []
        mount_violations = ["mount list is unreadable"]
    env_file = Path("/run/secrets/t3code.env")
    env_file_bytes = env_file.stat().st_size if env_file.exists() else None
    secret_names = sorted(
        {name for names in env_names.values() for name in names if name in AUTH_NAMES}
        | {name for names in instances.values() for name in names if name in AUTH_NAMES}
        | ({str(auth_path) for auth_path, present in auth.items() if present})
    )
    state = "observed" if env_names and settings_ok and instances else "unknown"
    print(json.dumps({
        "state": state,
        "env_names": env_names,
        "auth_paths": auth,
        "provider_instances": sorted(instances),
        "provider_environment_names": instances,
        "opencode_providers": providers,
        "mounts": mounts,
        "mount_violations": mount_violations,
        "env_file_bytes": env_file_bytes,
        "secret_names": secret_names,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
