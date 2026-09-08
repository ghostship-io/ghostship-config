import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path


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
        query = urllib.parse.urlencode(
            {
                "status": "up" if fresh else "down",
                "msg": "Recent successful run"
                if fresh
                else "Successful run missing or stale",
            }
        )
        try:
            with urllib.request.urlopen(
                f"http://{ip}:3001/api/push/{tokens[name]}?{query}", timeout=15
            ) as response:
                if not json.load(response).get("ok"):
                    raise RuntimeError()
        except (OSError, ValueError, RuntimeError):
            raise RuntimeError(f"Could not submit {name} heartbeat") from None


if __name__ == "__main__":
    main()
