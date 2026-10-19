"""Start tool maintenance as soon as T3 Code would advise a provider update.

T3 compares each provider's version with the npm registry's `latest` tag and
shows "Update available" when the install is behind. This watcher reads the
same registry endpoints and the installed manifests, then starts the guarded
tool updater once per newly published version. The updater still waits for
T3 to be idle; T3's periodic provider probe clears the notice afterwards.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Packages T3 checks for the providers this container installs, with the
# manifest of the active installation relative to the tools root.
PROVIDERS = (
    ("@openai/codex", "npm/lib/node_modules/@openai/codex/package.json"),
    (
        "@anthropic-ai/claude-code",
        "npm/lib/node_modules/@anthropic-ai/claude-code/package.json",
    ),
    ("@opencode/cli", "opencode/current/lib/node_modules/@opencode/cli/package.json"),
    ("@xai-official/grok", "grok/node_modules/@xai-official/grok/package.json"),
)
REGISTRY = "https://registry.npmjs.org"
UPDATE_UNIT = "t3code-tool-auto-update.service"


def log(message):
    print(f"info: {message}", file=sys.stderr)


def installed_version(manifest):
    try:
        version = json.loads(manifest.read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) and version else None


def fetch_latest(package):
    url = f"{REGISTRY}/{urllib.parse.quote(package, safe='')}/latest"
    request = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        version = json.load(response).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"registry returned no version for {package}")
    return version


def version_key(version):
    match = re.match(r"v?(\d+(?:\.\d+)*)(-.+)?$", version.strip())
    if not match:
        return None
    numbers = tuple(int(part) for part in match.group(1).split("."))
    # A release sorts after its prereleases, matching semver precedence.
    return numbers, match.group(2) is None


def is_behind(installed, latest):
    current, newest = version_key(installed), version_key(latest)
    if current is None or newest is None:
        return installed != latest
    return newest > current


def outdated(tools_root, fetch=fetch_latest):
    found = []
    for package, manifest in PROVIDERS:
        installed = installed_version(tools_root / manifest)
        if installed is None:
            continue
        try:
            latest = fetch(package)
        except (OSError, ValueError) as error:  # Includes URLError and bad JSON.
            log(f"could not resolve the latest {package}: {error}")
            continue
        if is_behind(installed, latest):
            found.append((package, installed, latest))
    return found


def check(tools_root, state_file, start_update, fetch=fetch_latest):
    """Return True when the updater was started for newly published versions."""
    found = outdated(tools_root, fetch)
    if not found:
        state_file.unlink(missing_ok=True)
        return False
    key = "|".join(sorted(f"{package}:{latest}" for package, _, latest in found))
    try:
        if state_file.read_text().strip() == key:
            log(
                "provider updates were already requested; the updater retries on its own schedule"
            )
            return False
    except OSError:
        pass
    for package, installed, latest in found:
        log(f"{package} {installed} is behind {latest}")
    start_update()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_name(state_file.name + ".tmp")
    temporary.write_text(key + "\n")
    os.replace(temporary, state_file)
    log(f"started {UPDATE_UNIT}")
    return True


def start_update():
    subprocess.run(["systemctl", "start", "--no-block", UPDATE_UNIT], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-root", type=Path, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    args = parser.parse_args()
    check(args.tools_root, args.state_file, start_update)


if __name__ == "__main__":
    main()
