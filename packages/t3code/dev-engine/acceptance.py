"""Run INSIDE a disposable T3 candidate, after starting its localhost bridge.

Never selects the production engine: verifies rootless Podman candidate storage
before creating anything. Uses only uniquely named disposable Podman objects
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
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

# The client resolves a project-scoped alias and then talks to that service.
# Netavark/aardvark DNS answers the alias only inside the project's network.
DNS_CLIENT_SCRIPT = r"""
import json, socket, sys, time

name, port = sys.argv[1], int(sys.argv[2])
report = {"name": name, "port": port}
try:
    infos = socket.getaddrinfo(name, port, type=socket.SOCK_STREAM)
except OSError as error:
    report["resolved"] = False
    report["error"] = str(error)
    print(json.dumps(report))
    sys.exit(2)
report["resolved"] = True
report["addresses"] = sorted({info[4][0] for info in infos})
with open("/etc/resolv.conf") as handle:
    report["resolver"] = handle.read()
deadline = time.monotonic() + 30
status = b""
while time.monotonic() < deadline:
    try:
        with socket.create_connection((name, port), 2) as connection:
            connection.sendall(b"GET / HTTP/1.0\r\nHost: " + name.encode() + b"\r\n\r\n")
            status = connection.recv(128)
        break
    except OSError as error:
        report["connect_error"] = str(error)
        time.sleep(0.5)
report["http_status"] = status.split(b"\r\n", 1)[0].decode("utf-8", "replace")
print(json.dumps(report))
sys.exit(0 if " 200 " in report["http_status"] else 1)
"""

# The same alias must stay invisible from a network outside the project.
ISOLATION_SCRIPT = r"""
import json, socket, sys

name = sys.argv[1]
try:
    infos = socket.getaddrinfo(name, 80, type=socket.SOCK_STREAM)
except OSError as error:
    print(json.dumps({"resolved": False, "error": str(error)}))
    sys.exit(0)
print(json.dumps({"resolved": True, "addresses": sorted({i[4][0] for i in infos})}))
sys.exit(1)
"""

# The marker must outlive the container that wrote it.
VOLUME_WRITE_SCRIPT = r"""
import os, pathlib

target = pathlib.Path("/data/t3code-acceptance.txt")
target.write_text(os.environ["T3_ACCEPTANCE_MARKER"])
print(target.read_text())
"""

VOLUME_READ_SCRIPT = r"""
import os, pathlib, sys

target = pathlib.Path("/data/t3code-acceptance.txt")
expected = os.environ["T3_ACCEPTANCE_MARKER"]
try:
    actual = target.read_text()
except OSError as error:
    print(f"no persisted content: {error}")
    sys.exit(1)
print(actual)
sys.exit(0 if actual == expected else 1)
"""

TTY_SCRIPT = "import sys; sys.exit(0 if sys.stdout.isatty() else 1)"


class CommandFailure(RuntimeError):
    """A required Podman probe failed and must be reported, not hidden."""

    def __init__(self, arguments, result):
        self.arguments = list(arguments)
        self.result = result
        super().__init__(f"podman {arguments[0]} exited {result.returncode}")


def list_ids(command, *arguments):
    """Return the object ids printed by a podman listing command."""
    try:
        result = command(*arguments, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def last_json_object(text):
    """Return the last JSON object a container printed."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def project_networks(command, project):
    """Return the compose project's own networks and their address pools."""
    details = {}
    names = list_ids(
        command,
        "network",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--format",
        "{{.Name}}",
    )
    for name in names:
        inspected = command("network", "inspect", name, check=False)
        if inspected.returncode != 0:
            continue
        try:
            rows = json.loads(inspected.stdout or "[]")
        except json.JSONDecodeError:
            continue
        for row in rows:
            details[name] = {
                "driver": row.get("Driver", ""),
                "subnets": [
                    entry["Subnet"]
                    for entry in row.get("IPAM", {}).get("Config", [])
                    if "Subnet" in entry
                ],
            }
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/var/run/podman/podman.sock")
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
    parser.add_argument("--subid-start", type=int, default=2000000)
    parser.add_argument("--image", default="docker.io/library/python:3.13-alpine")
    args = parser.parse_args()
    control = json.loads(args.control_report.read_text())
    if not 0 <= time.time() - control["observed_at"] <= 300:
        parser.error("control canary report is stale or from the future")
    for endpoint in args.denied_endpoint:
        ipaddress.IPv4Address(endpoint.rsplit(":", 1)[0])
        if control.get("endpoints", {}).get(endpoint) is not True:
            parser.error(f"control did not prove this endpoint live: {endpoint}")
    engine = ["podman", "--remote", "--url", f"unix://{args.socket}"]

    def command(*arguments, check=True, quiet=False, **kwargs):
        argv = [*engine, *arguments]
        if arguments[0] == "compose":
            argv = [
                "podman",
                "--remote",
                "--url",
                f"unix://{args.socket}",
                "compose",
                *arguments[1:],
            ]
        result = subprocess.run(
            argv,
            check=False,
            text=True,
            capture_output=True,
            timeout=180,
            **kwargs,
        )
        if result.returncode != 0:
            # Report the failure now. A later error must never hide the first
            # broken probe, and the collected results must not be lost with it.
            if not quiet:
                print(
                    f"podman {arguments[0]} exited {result.returncode}: "
                    f"{' '.join(str(item) for item in arguments[1:])}\n"
                    f"{result.stderr[-2000:]}",
                    file=sys.stderr,
                )
            if check:
                raise CommandFailure(arguments, result)
        return result

    info = json.loads(command("info", "--format", "{{json .}}").stdout)
    # Podman has no daemon-label equivalent. Native info identifies the actual
    # rootless storage. Production uses a different graph root; refuse before
    # the first mutation, even when the socket was redirected.
    if (
        info.get("store", {}).get("graphRoot") != "/var/lib/t3code-podman/candidate"
        or info.get("host", {}).get("security", {}).get("rootless") is not True
    ):
        parser.error("refusing to mutate a non-candidate Podman store")
    results = []

    def record(name, good, detail=""):
        results.append({"check": name, "passed": bool(good), "detail": detail})

    record(
        "rootless + systemd cgroup v2",
        info["host"]["security"]["rootless"]
        and info["host"]["cgroupManager"] == "systemd"
        and info["host"]["cgroupVersion"] == "v2",
    )
    tag = f"t3code-acceptance-{uuid.uuid4().hex}"
    # Every object this run creates carries the unique tag, so cleanup can
    # never reach a resource that belongs to somebody else.
    service_alias = f"{tag}-web"
    failure = None
    try:
        with tempfile.TemporaryDirectory(
            prefix=".t3-podman-acceptance-", dir=args.workspace
        ) as directory:
            source = Path(directory)
            # Project owners opt in to nonroot writes. Never change an existing
            # project here: this grant is limited to the disposable fixture.
            owner = os.getuid()
            if owner != 3000:
                parser.error("run as the T3 workspace owner (UID 3000)")
            grants = [
                f"{prefix}u:{args.subid_start + uid - 1}:rwx"
                for uid in (3000, 1000)
                for prefix in ("", "d:")
            ]
            subprocess.run(
                ["setfacl", "-m", ",".join([*grants, f"d:u:{owner}:rwx"]), str(source)],
                check=True,
            )

            def attempt(*arguments):
                """Run a cleanup command without letting one failure hide others."""
                try:
                    command(*arguments, check=False, quiet=True)
                except (OSError, subprocess.SubprocessError):
                    pass

            def cleanup():
                """Remove every disposable object created under this unique tag."""
                attempt(
                    "compose",
                    "-p",
                    tag,
                    "-f",
                    str(source / "compose.json"),
                    "down",
                    "--volumes",
                    "--remove-orphans",
                )
                # Only two exact keys may match: this run's own label and the
                # compose project this run created. Nothing else is touched.
                for kind, listing in (
                    ("rm", ("ps", "-aq")),
                    ("network rm", ("network", "ls", "-q")),
                    ("volume rm", ("volume", "ls", "-q")),
                ):
                    identifiers = list_ids(
                        command,
                        *listing,
                        "--filter",
                        f"label=t3code.acceptance={tag}",
                    )
                    identifiers += list_ids(
                        command,
                        *listing,
                        "--filter",
                        f"label=com.docker.compose.project={tag}",
                    )
                    for identifier in dict.fromkeys(identifiers):
                        attempt(*kind.split(), "-f", identifier)
                attempt("image", "rm", "-f", tag)

            try:
                (source / "Containerfile").write_text(
                    f"FROM {args.image}\nRUN python -c 'import socket; assert socket.getaddrinfo(\"example.com\", 443)'\n"
                )
                build = command(
                    "build",
                    "--label",
                    f"t3code.acceptance={tag}",
                    "-t",
                    tag,
                    str(source),
                    check=False,
                )
                record(
                    "build + public DNS", build.returncode == 0, build.stderr[-1000:]
                )
                for container_uid in (0, 3000, 1000):
                    probe = command(
                        "run",
                        "--rm",
                        "--label",
                        f"t3code.acceptance={tag}",
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
                    expected_owner = (
                        owner
                        if container_uid == 0
                        else args.subid_start + container_uid - 1
                    )
                    writable = False
                    if probe.returncode == 0:
                        correct_owner = (
                            output.stat().st_uid == expected_owner
                            and (output / "file").stat().st_uid == expected_owner
                        )
                        # Exercise the T3 owner's actual operations, rather than
                        # inferring them from mode bits or os.access().
                        (output / "file").write_text("edited by T3")
                        edited = (output / "file").read_text() == "edited by T3"
                        (output / "file").unlink()
                        output.rmdir()
                        writable = correct_owner and edited and not output.exists()
                    record(
                        f"bind writes as container UID {container_uid}; T3 edit/delete; host UID {expected_owner}",
                        writable,
                        probe.stderr[-600:],
                    )
                limit = command(
                    "run",
                    "--rm",
                    "--label",
                    f"t3code.acceptance={tag}",
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
                    "--label",
                    f"t3code.acceptance={tag}",
                    args.image,
                    "python",
                    "-c",
                    "import urllib.request; assert urllib.request.urlopen('https://example.com', timeout=10).status == 200",
                    check=False,
                )
                record(
                    "outbound HTTPS", internet.returncode == 0, internet.stderr[-600:]
                )
                tty = command(
                    "run",
                    "--rm",
                    "--label",
                    f"t3code.acceptance={tag}",
                    "--tty",
                    args.image,
                    "python",
                    "-c",
                    TTY_SCRIPT,
                    check=False,
                )
                # Without a TTY the same probe must fail, otherwise the positive
                # result would not prove that the engine allocated a terminal.
                plain = command(
                    "run",
                    "--rm",
                    "--label",
                    f"t3code.acceptance={tag}",
                    args.image,
                    "python",
                    "-c",
                    TTY_SCRIPT,
                    check=False,
                    quiet=True,
                )
                record(
                    "interactive TTY allocation",
                    tty.returncode == 0 and plain.returncode != 0,
                    json.dumps(
                        {
                            "tty_exit": tty.returncode,
                            "without_tty_exit": plain.returncode,
                            "tty_stderr": tty.stderr[-300:],
                        }
                    ),
                )
                # Host network / privileged intentionally exercise the slirp bypass
                # boundary. In rootless mode these remain within the outer netns.
                for control_number, endpoint in enumerate(args.denied_endpoint, 1):
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
                        "--label",
                        f"t3code.acceptance={tag}",
                        "--privileged",
                        "--network=host",
                        args.image,
                        "python",
                        "-c",
                        probe_code,
                        check=False,
                    )
                    record(
                        f"host-network private/local canary denied (control {control_number})",
                        blocked.returncode == 0
                        and json.loads(blocked.stdout or "{}").get("endpoint")
                        == endpoint
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
                                    # Every container of this run carries the
                                    # run label, so cleanup owns it by label.
                                    "labels": {"t3code.acceptance": tag},
                                    # A unique alias keeps the project name out of
                                    # any public resolver and out of other projects.
                                    "networks": {
                                        "default": {"aliases": [service_alias]}
                                    },
                                },
                                "client": {
                                    "image": args.image,
                                    "labels": {"t3code.acceptance": tag},
                                    "command": [
                                        "python",
                                        "-c",
                                        DNS_CLIENT_SCRIPT,
                                        service_alias,
                                        "8080",
                                    ],
                                },
                            }
                        }
                    )
                )
                up = command(
                    "compose",
                    "-p",
                    tag,
                    "-f",
                    str(compose),
                    "up",
                    "-d",
                    "web",
                    check=False,
                )
                if up.returncode != 0:
                    # A failed project start is a gate failure, not a reason to
                    # lose the diagnostics of every other probe.
                    record(
                        "Compose project starts on the isolated project network",
                        False,
                        up.stderr[-600:],
                    )
                published = command(
                    "compose",
                    "-p",
                    tag,
                    "-f",
                    str(compose),
                    "port",
                    "web",
                    "8080",
                    check=False,
                )
                forwarded = False
                detail = published.stdout.strip()
                if not detail:
                    detail = published.stderr[-600:] or up.stderr[-600:]
                if published.returncode == 0 and published.stdout.strip():
                    port = int(published.stdout.strip().rsplit(":", 1)[1])
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
                    detail,
                )
                networks = project_networks(command, tag)
                client = command(
                    "compose",
                    "-p",
                    tag,
                    "-f",
                    str(compose),
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "client",
                    check=False,
                )
                report = last_json_object(client.stdout)
                addresses = report.get("addresses", [])
                subnets = [
                    ipaddress.ip_network(subnet)
                    for details in networks.values()
                    for subnet in details["subnets"]
                ]
                inside = bool(addresses) and all(
                    any(ipaddress.ip_address(address) in subnet for subnet in subnets)
                    for address in addresses
                )
                embedded_dns = bool(report.get("resolver", "").strip())
                isolated = bool(networks) and "bridge" not in networks
                record(
                    "Compose service-to-service DNS on the isolated project network",
                    client.returncode == 0
                    and report.get("resolved") is True
                    and inside
                    and embedded_dns
                    and isolated,
                    json.dumps(
                        {
                            "resolved": report.get("resolved"),
                            "addresses": addresses,
                            "networks": networks,
                            "resolver": report.get("resolver", "").strip(),
                            "http_status": report.get("http_status", ""),
                            "error": report.get("error", ""),
                            "connect_error": report.get("connect_error", ""),
                            "compose_up": up.stderr[-300:],
                            "stderr": client.stderr[-300:],
                        }
                    ),
                )
                isolation_network = f"{tag}-isolation"
                created = command(
                    "network",
                    "create",
                    "--driver",
                    "bridge",
                    "--label",
                    f"t3code.acceptance={tag}",
                    isolation_network,
                    check=False,
                )
                if created.returncode != 0:
                    record(
                        "Compose service name is not resolvable outside the project network",
                        False,
                        created.stderr[-600:],
                    )
                else:
                    outside = command(
                        "run",
                        "--rm",
                        "--label",
                        f"t3code.acceptance={tag}",
                        "--network",
                        isolation_network,
                        args.image,
                        "python",
                        "-c",
                        ISOLATION_SCRIPT,
                        service_alias,
                        check=False,
                    )
                    payload = last_json_object(outside.stdout)
                    record(
                        "Compose service name is not resolvable outside the project network",
                        outside.returncode == 0 and payload.get("resolved") is False,
                        json.dumps(
                            {
                                "resolved": payload.get("resolved"),
                                "addresses": payload.get("addresses", []),
                                "error": payload.get("error", ""),
                                "stderr": outside.stderr[-300:],
                            }
                        ),
                    )
                volume = f"{tag}-data"
                marker = f"t3code-acceptance-{uuid.uuid4().hex}"
                made = command(
                    "volume",
                    "create",
                    "--label",
                    f"t3code.acceptance={tag}",
                    volume,
                    check=False,
                )
                writer = f"{tag}-keeper-write"
                reader = f"{tag}-keeper-read"
                wrote = command(
                    "run",
                    "--name",
                    writer,
                    "--label",
                    f"t3code.acceptance={tag}",
                    "--env",
                    f"T3_ACCEPTANCE_MARKER={marker}",
                    "--volume",
                    f"{volume}:/data",
                    args.image,
                    "python",
                    "-c",
                    VOLUME_WRITE_SCRIPT,
                    check=False,
                )
                writer_id = command(
                    "inspect", "--format", "{{.Id}}", writer, check=False
                ).stdout.strip()
                # Drop the writing container: only the named volume may keep the
                # data, so the next container proves persistence, not a layer.
                attempt("rm", "-f", writer)
                read = command(
                    "run",
                    "--name",
                    reader,
                    "--label",
                    f"t3code.acceptance={tag}",
                    "--env",
                    f"T3_ACCEPTANCE_MARKER={marker}",
                    "--volume",
                    f"{volume}:/data",
                    args.image,
                    "python",
                    "-c",
                    VOLUME_READ_SCRIPT,
                    check=False,
                )
                reader_id = command(
                    "inspect", "--format", "{{.Id}}", reader, check=False
                ).stdout.strip()
                record(
                    "named volume content survives container recreation",
                    made.returncode == 0
                    and wrote.returncode == 0
                    and read.returncode == 0
                    and bool(writer_id)
                    and bool(reader_id)
                    and writer_id != reader_id,
                    json.dumps(
                        {
                            "volume": volume,
                            "writer_container": writer_id,
                            "reader_container": reader_id,
                            "write_exit": wrote.returncode,
                            "read_exit": read.returncode,
                            "write_stderr": wrote.stderr[-300:],
                            "read_stderr": read.stderr[-300:],
                        }
                    ),
                )
            finally:
                cleanup()
    except (
        CommandFailure,
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        IndexError,
    ) as error:
        # Keep every collected result: an aborted probe must not discard
        # the evidence that the earlier probes produced.
        failure = error
        detail = f"{type(error).__name__}: {error}"
        captured = getattr(error, "stderr", None)
        if captured:
            detail = f"{detail}\n{captured[-600:]}"
        record(
            "acceptance run completed without an internal error",
            False,
            detail,
        )
    finally:
        # The report is the deliverable: print it even when a probe aborts.
        print(json.dumps(results, indent=2))
    if failure is not None:
        raise failure
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
