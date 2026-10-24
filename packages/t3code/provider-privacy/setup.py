"""Apply Claude Code's nonessential-traffic and feedback opt-outs before T3 starts."""

import json
import os
import sys
import tempfile
from pathlib import Path

PRIVACY = {
    # One switch disables metrics, error reporting, surveys and feature flags.
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_FEEDBACK_COMMAND": "1",
    "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".claude-privacy-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def configure(home):
    path = home / ".claude/settings.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Claude settings must be an object")
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        raise ValueError("Claude settings env must be an object")
    changed = not path.exists() or any(env.get(key) != value for key, value in PRIVACY.items())
    env.update(PRIVACY)
    if changed:
        atomic_json(path, data)
    return changed


def main():
    try:
        configure(Path.home())
        return 0
    except Exception as exc:
        print(f"Claude privacy setup unavailable: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
