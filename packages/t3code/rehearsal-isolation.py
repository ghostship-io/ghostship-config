#!/usr/bin/env python3
"""Read-only in-candidate isolation observer for candidate rehearsal."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


# Two deliberate decisions, both fail-closed:
#   * Every observed environment name must be in this explicit non-secret
#     allowlist with a reason. Anything else is flagged, even if it does not
#     look like a credential.
#   * A secret-like name is always a violation unless an operator adds it to
#     the allowlist with a reason in review.
SECRET_NAME_RE = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|AUTH|SESSION|COOKIE|CREDENTIAL", re.IGNORECASE)
ENV_ALLOWLIST = {
    "PATH": "process search path",
    "HOME": "candidate home path",
    "HOSTNAME": "container hostname",
    "LANG": "locale",
    "LANGUAGE": "locale",
    "LC_ALL": "locale",
    "LC_CTYPE": "locale",
    "LC_MESSAGES": "locale",
    "TERM": "terminal type",
    "USER": "runtime user name",
    "LOGNAME": "runtime user name",
    "SHELL": "runtime shell path",
    "PWD": "working directory",
    "OLDPWD": "working directory",
    "TMPDIR": "temporary directory path",
    "TEMP": "temporary directory path",
    "TMP": "temporary directory path",
    "TZ": "timezone",
    "XDG_CONFIG_HOME": "config directory path",
    "XDG_CACHE_HOME": "cache directory path",
    "XDG_DATA_HOME": "data directory path",
    "XDG_STATE_HOME": "state directory path",
    "XDG_RUNTIME_DIR": "runtime directory path",
    "DBUS_SESSION_BUS_ADDRESS": "session bus path",
    "NOTIFY_SOCKET": "systemd notification socket path",
    "INVOCATION_ID": "systemd invocation identifier",
    "JOURNAL_STREAM": "systemd journal stream descriptor",
    "LISTEN_FDS": "systemd socket descriptor count",
    "LISTEN_PID": "systemd socket process id",
    "LISTEN_FDNAMES": "systemd socket descriptor names",
    "SYSTEMD_EXEC_PID": "systemd exec process id",
    "WATCHDOG_PID": "systemd watchdog process id",
    "WATCHDOG_USEC": "systemd watchdog interval",
    "NODE_ENV": "node mode",
    "NODE_EXTRA_CA_CERTS": "node CA bundle path",
    "NODE_NO_WARNINGS": "node warning suppression",
    "GHOSTSHIP_ROUTE_POLICY_PATH": "route policy input path",
    "GHOSTSHIP_MODEL_EVIDENCE_PATH": "model evidence output path",
    "GHOSTSHIP_MODEL_RANKINGS_PATH": "model ranking input path",
    "GHOSTSHIP_COORDINATOR_URL": "coordinator URL",
    "GHOSTSHIP_COORDINATOR_TOKEN_FILE": "coordinator token file path, not a value",
    "OPENCODE_DISABLE_FREE_MODELS": "anonymous Zen setting",
    "OPENCODE_MODELS_PATH": "model catalog path",
    "OPENCODE_CONFIG": "opencode config path",
    "OPENCODE_CONFIG_DIR": "opencode config directory path",
}
AUTH_FILE_RE = re.compile(r"^(auth\.json|credentials.*|hosts\.yml)$", re.IGNORECASE)
AUTH_SCAN_DEPTH = 5
AUTH_SCAN_MAX_ENTRIES = 50000


def classify_env_names(names):
    """Every name is allowlisted or a violation; secret-like names are noted."""
    allowed = []
    secret_like = []
    unrecognized = []
    for name in sorted({name for name in names if isinstance(name, str) and name}):
        if name in ENV_ALLOWLIST:
            allowed.append(name)
            continue
        if SECRET_NAME_RE.search(name):
            secret_like.append(name)
        else:
            unrecognized.append(name)
    return {
        "allowed": allowed,
        "secret_like": secret_like,
        "unrecognized": unrecognized,
        "violations": sorted(secret_like + unrecognized),
    }


def find_auth_artifacts(home, max_depth=AUTH_SCAN_DEPTH,
                        max_entries=AUTH_SCAN_MAX_ENTRIES):
    """Find credential-shaped files by name under HOME; never read them."""
    home = Path(home)
    findings = []
    visited = 0
    truncated = False
    if not home.is_dir():
        return findings, {"visited": 0, "truncated": False,
                          "max_depth": max_depth, "scope": str(home)}
    for base, directories, files in os.walk(home, followlinks=False):
        relative_depth = len(Path(base).relative_to(home).parts)
        if relative_depth >= max_depth:
            directories[:] = []
        directories[:] = [name for name in directories
                          if not (Path(base) / name).is_symlink()]
        for name in files:
            visited += 1
            if visited > max_entries:
                truncated = True
                break
            if AUTH_FILE_RE.match(name):
                findings.append(str((Path(base) / name).relative_to(home)))
        if truncated:
            break
    return sorted(findings), {"visited": visited, "truncated": truncated,
                              "max_depth": max_depth, "scope": str(home)}


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


def _processes():
    """Selected process IDs and their comm values, for the report."""
    found = {}
    main = _main_pid()
    if main:
        try:
            found[main] = Path(f"/proc/{main}/comm").read_text().strip()
        except OSError:
            found[main] = "unknown"
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or entry.name in found:
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if any(token in comm.lower() for token in ("t3", "opencode", "node", "bun")):
            found[entry.name] = comm
    return found


def main():
    home = Path(os.environ.get("HOME", "/home/t3code"))
    auth_artifacts, auth_scan = find_auth_artifacts(home)
    processes = _processes()
    env_names = {}
    for pid in processes:
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
            if (source.startswith("/srv/apps/t3code")
                    or target.startswith("/srv/apps/t3code")):
                mount_violations.append(f"production T3 path is mounted at {target}")
            if (target.startswith("/run/secrets/")
                    and target != "/run/secrets/t3code.env"):
                mount_violations.append(f"unexpected secret mount at {target}")
            if (AUTH_FILE_RE.match(Path(source).name)
                    or AUTH_FILE_RE.match(Path(target).name)):
                mount_violations.append(f"credential-shaped path is mounted at {target}")
    except OSError:
        mounts = []
        mount_violations = ["mount list is unreadable"]
    env_file = Path("/run/secrets/t3code.env")
    if env_file.exists():
        env_file_present = True
        try:
            env_file_bytes = env_file.stat().st_size
            env_file_state = "empty" if env_file_bytes == 0 else "not_empty"
        except OSError:
            env_file_bytes = None
            env_file_state = "unreadable"
    else:
        env_file_present = False
        env_file_bytes = None
        env_file_state = "absent"
    observed_names = {name for names in env_names.values() for name in names}
    observed_names.update(name for names in instances.values() for name in names)
    classification = classify_env_names(observed_names)
    secret_names = sorted(set(classification["secret_like"]) | set(auth_artifacts))
    state = ("observed" if env_names and settings_ok and instances
             and not auth_scan["truncated"] else "unknown")
    print(json.dumps({
        "state": state,
        "processes": processes,
        "env_names": env_names,
        "env_allowlisted": classification["allowed"],
        "env_secret_names": classification["secret_like"],
        "env_unrecognized_names": classification["unrecognized"],
        "env_violations": classification["violations"],
        "auth_artifacts": auth_artifacts,
        "auth_scan": auth_scan,
        "provider_instances": sorted(instances),
        "provider_environment_names": instances,
        "opencode_providers": providers,
        "mounts": mounts,
        "mount_violations": mount_violations,
        "env_file": {"present": env_file_present, "bytes": env_file_bytes,
                     "state": env_file_state},
        "env_file_bytes": env_file_bytes,
        "secret_names": secret_names,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
