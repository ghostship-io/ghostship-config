"""Run INSIDE a disposable T3 candidate, after starting its localhost bridge.

Never selects the active legacy engine: verifies the candidate daemon label
before creating anything. Uses only uniquely named disposable Docker objects
and a temporary directory in the mapped workspace. A nonzero exit is a real
enablement gate, including nonroot bind-write incompatibility. This does NOT
prove all kernel/firewall isolation; also inspect host nft policy, rootfs mounts,
socket permissions and aggregate cgroups in an isolated host/VM acceptance run.
"""

import argparse
import ipaddress
import json
import os
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/var/run/docker.sock")
    parser.add_argument("--workspace", default="/workspace", type=Path)
    parser.add_argument(
        "--control-report",
        required=True,
        type=Path,
        help="Fresh canary-probe.py report from a permitted control namespace",
    )
    parser.add_argument(
        "--denied-endpoint",
        action="append",
        required=True,
        help="Known listening HOST/PUBLIC-HOST/LAN IPv4:port canary; repeat for each",
    )
    parser.add_argument("--image", default="python:3.13-alpine")
    args = parser.parse_args()
    control = json.loads(args.control_report.read_text())
    if not 0 <= time.time() - control["observed_at"] <= 300:
        parser.error("control canary report is stale or from the future")
    for endpoint in args.denied_endpoint:
        ipaddress.IPv4Address(endpoint.rsplit(":", 1)[0])
        if control.get("endpoints", {}).get(endpoint) is not True:
            parser.error(f"control did not prove this endpoint live: {endpoint}")
    docker = ["docker", "--host", f"unix://{args.socket}"]

    def command(*arguments, check=True, **kwargs):
        return subprocess.run(
            [*docker, *arguments],
            check=check,
            text=True,
            capture_output=True,
            timeout=180,
            **kwargs,
        )

    info = json.loads(command("info", "--format", "{{json .}}").stdout)
    if "ghostship.t3code-docker=candidate" not in info.get("Labels", []):
        parser.error(
            "refusing to mutate a daemon without the dedicated candidate label"
        )
    results = []

    def record(name, good, detail=""):
        results.append({"check": name, "passed": bool(good), "detail": detail})

    record(
        "rootless + systemd cgroup v2",
        any("rootless" in item for item in info["SecurityOptions"])
        and info["CgroupDriver"] == "systemd"
        and info["CgroupVersion"] == "2",
    )
    tag = f"t3code-acceptance-{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(
        prefix=".t3-docker-acceptance-", dir=args.workspace
    ) as directory:
        source = Path(directory)
        try:
            (source / "Dockerfile").write_text(
                f"FROM {args.image}\nRUN python -c 'import socket; assert socket.getaddrinfo(\"example.com\", 443)'\n"
            )
            build = command("build", "-t", tag, str(source), check=False)
            record("build + public DNS", build.returncode == 0, build.stderr[-1000:])
            for container_uid in (0, 3000, 1000):
                probe = command(
                    "run",
                    "--rm",
                    "--user",
                    f"{container_uid}:{container_uid}",
                    "--mount",
                    f"type=bind,src={source},dst=/probe",
                    args.image,
                    "python",
                    "-c",
                    f"from pathlib import Path; p=Path('/probe/u{container_uid}'); p.mkdir(); (p/'file').write_text('shared')",
                    check=False,
                )
                output = source / f"u{container_uid}"
                # Every accepted producer must leave files cleanable by T3's
                # UID3000, without host root or recursively changing ownership.
                writable = (
                    probe.returncode == 0
                    and output.stat().st_uid == 3000
                    and os.access(output, os.W_OK)
                )
                record(
                    f"bind writes as container UID {container_uid}, host ownership 3000",
                    writable,
                    probe.stderr[-600:],
                )
            limit = command(
                "run",
                "--rm",
                "--memory=64m",
                "--pids-limit=64",
                args.image,
                "python",
                "-c",
                "from pathlib import Path; assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == '67108864'; assert Path('/sys/fs/cgroup/pids.max').read_text().strip() == '64'",
                check=False,
            )
            record(
                "per-container memory/pids limits",
                limit.returncode == 0,
                limit.stderr[-600:],
            )
            internet = command(
                "run",
                "--rm",
                args.image,
                "python",
                "-c",
                "import urllib.request; assert urllib.request.urlopen('https://example.com', timeout=10).status == 200",
                check=False,
            )
            record("outbound HTTPS", internet.returncode == 0, internet.stderr[-600:])
            # Host network / privileged intentionally exercise the slirp bypass
            # boundary. In rootless mode these remain within the outer netns.
            for endpoint in args.denied_endpoint:
                address, port = endpoint.rsplit(":", 1)
                probe_code = (
                    "import errno,json,socket,sys\n"
                    f"endpoint={endpoint!r}\n"
                    f"try: socket.create_connection(({address!r},{int(port)}),2)\n"
                    "except OSError as e:\n"
                    " allowed=isinstance(e,TimeoutError) or e.errno in (errno.EACCES,errno.ECONNREFUSED,errno.ETIMEDOUT,errno.EHOSTUNREACH,errno.ENETUNREACH)\n"
                    " print(json.dumps({'endpoint':endpoint,'blocked':allowed,'errno':e.errno}))\n"
                    " sys.exit(0 if allowed else 2)\n"
                    "print(json.dumps({'endpoint':endpoint,'blocked':False})); sys.exit(1)"
                )
                blocked = command(
                    "run",
                    "--rm",
                    "--privileged",
                    "--network=host",
                    args.image,
                    "python",
                    "-c",
                    probe_code,
                    check=False,
                )
                record(
                    f"host-network private/local canary denied {endpoint}",
                    blocked.returncode == 0
                    and json.loads(blocked.stdout or "{}").get("endpoint") == endpoint
                    and json.loads(blocked.stdout or "{}").get("blocked") is True,
                    blocked.stderr[-600:],
                )
            compose = source / "compose.json"
            compose.write_text(
                json.dumps(
                    {
                        "services": {
                            "web": {
                                "image": args.image,
                                "command": ["python", "-m", "http.server", "8080"],
                                "ports": ["8080"],
                            }
                        }
                    }
                )
            )
            command("compose", "-p", tag, "-f", str(compose), "up", "-d")
            published = command(
                "compose", "-p", tag, "-f", str(compose), "port", "web", "8080"
            ).stdout.strip()
            port = int(published.rsplit(":", 1)[1])
            forwarded = False
            for _ in range(30):
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}", timeout=1
                    ) as response:
                        forwarded = response.status == 200
                        break
                except OSError:
                    time.sleep(0.2)
            record(
                "Compose random published port through T3 localhost bridge",
                forwarded,
                published,
            )
        finally:
            command(
                "compose",
                "-p",
                tag,
                "-f",
                str(source / "compose.json"),
                "down",
                "--volumes",
                check=False,
            )
            command("image", "rm", tag, check=False)
    print(json.dumps(results, indent=2))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
