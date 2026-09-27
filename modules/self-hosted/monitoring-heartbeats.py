import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path


def container_health(name):
    result = subprocess.run(
        [
            "podman",
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}",
            name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return False, "Container is missing or cannot be inspected"
    state, _, health = result.stdout.strip().partition("|")
    if state != "running":
        return False, f"Container state is {state or 'unknown'}"
    if health and health != "healthy":
        return False, f"Container health is {health}"
    return True, "Container is running and healthy"


def push_status(ip, token, fresh, message):
    query = urllib.parse.urlencode(
        {"status": "up" if fresh else "down", "msg": message}
    )
    with urllib.request.urlopen(
        f"http://{ip}:3001/api/push/{token}?{query}", timeout=15
    ) as response:
        if not json.load(response).get("ok"):
            raise RuntimeError()


def main():
    tokens = json.loads(
        Path("/var/lib/ghostship-monitoring/push.json").read_text()
    )
    ip = subprocess.check_output(
        [
            "podman",
            "inspect",
            "uptime-kuma",
            "--format",
            '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}',
        ],
        text=True,
    ).strip()
    for name, path, age in [
        ("backup", "/var/lib/ghostship-backup/last-success", 108000),
        (
            "updates",
            "/var/lib/ghostship-monitoring/last-update-success",
            129600,
        ),
    ]:
        try:
            elapsed = time.time() - int(Path(path).read_text().strip())
            fresh = 0 <= elapsed < age
        except (OSError, ValueError):
            fresh = False
        try:
            push_status(
                ip,
                tokens[name],
                fresh,
                "Recent successful run"
                if fresh
                else "Successful run missing or stale",
            )
        except (OSError, ValueError, RuntimeError):
            raise RuntimeError(f"Could not submit {name} heartbeat") from None
    for name, token in tokens.get("containers", {}).items():
        fresh, message = container_health(name)
        try:
            push_status(ip, token, fresh, message)
        except (OSError, ValueError, RuntimeError):
            raise RuntimeError(
                f"Could not submit {name} container heartbeat"
            ) from None


if __name__ == "__main__":
    main()
