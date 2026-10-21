"""Activate only committed rootless-engine candidate units; preserve active T3.

Run as host root with the built t3codeDockerCandidate JSON. `stop` removes these
runtime units, preserving the dedicated account and Docker data for inspection.
This never activates a system generation or changes the production T3 unit.
"""

import argparse
import fcntl
import grp
import json
import os
import pwd
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True, timeout=240).strip()


def identity():
    row = json.loads(run("podman", "inspect", "t3code"))[0]
    return [
        row["Id"],
        row["State"]["Pid"],
        row["State"]["StartedAt"],
        run("systemctl", "show", "podman-t3code.service", "-p", "MainPID", "--value"),
        run(
            "podman",
            "exec",
            "t3code",
            "systemctl",
            "show",
            "t3code-server.service",
            "-p",
            "MainPID",
            "--value",
        ),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("start", "stop"))
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run as host root")
    spec = json.loads(args.spec.read_text())
    if spec["user"] != "t3code-docker" or spec["uid"] != 62040:
        parser.error(
            "this candidate driver is restricted to the dedicated UID62040 account"
        )
    units = spec["units"]
    if any(not name.startswith("t3code-docker") or "/" in name for name in units):
        parser.error("unexpected unit name")
    parent = Path("/var/lib/ghostship/t3code-hardening")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = parent / "candidate.json"
    with (parent / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = identity()
        manager = "user@62040.service"
        files = {
            Path("/run/systemd/system") / name: text for name, text in units.items()
        }
        files[Path("/run/systemd/system/user@62040.service.d/50-t3-candidate.conf")] = (
            spec["manager"]
        )
        try:
            if args.operation == "stop":
                if not marker.exists() or json.loads(marker.read_text()) != spec:
                    raise RuntimeError(
                        "candidate ownership marker does not match; leaving units intact"
                    )
                run(
                    "systemctl",
                    "stop",
                    "t3code-docker.socket",
                    "t3code-docker-ports.socket",
                    "t3code-docker.service",
                    "t3code-docker-ports.service",
                    manager,
                    "t3code-docker-rootfs.service",
                    "t3code-docker-network.service",
                )
                for path, text in files.items():
                    if path.exists() and path.read_text() == text:
                        path.unlink()
                marker.unlink()
                run("systemctl", "daemon-reload")
                return
            if marker.exists():
                raise RuntimeError(
                    "candidate already staged; inspect it or stop with its original spec before retrying"
                )
            for path in files:
                if path.exists() or (Path("/etc/systemd/system") / path.name).exists():
                    raise RuntimeError(f"existing unit must be reviewed first: {path}")
            try:
                group = grp.getgrnam(spec["user"])
                assert group.gr_gid == spec["uid"]
            except KeyError:
                run("groupadd", "--gid", str(spec["uid"]), spec["user"])
            try:
                account = pwd.getpwnam(spec["user"])
                assert account.pw_uid == spec["uid"] and account.pw_gid == spec["uid"]
            except KeyError:
                run(
                    "useradd",
                    "--system",
                    "--uid",
                    str(spec["uid"]),
                    "--gid",
                    str(spec["uid"]),
                    "--home-dir",
                    spec["state"] + "/home",
                    "--no-create-home",
                    "--shell",
                    "/run/current-system/sw/bin/nologin",
                    spec["user"],
                )
            for name in (spec["state"], spec["state"] + "/home"):
                path = Path(name)
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chown(path, spec["uid"], spec["uid"])
            socket_dir = Path("/run/t3code-docker")
            socket_dir.mkdir(mode=0o750, exist_ok=True)
            os.chown(socket_dir, 0, grp.getgrnam("apps").gr_gid)
            # The engine receives only this closure in the isolated T3 store.
            gcroot = Path(
                "/srv/apps/t3code/nix-root/nix/var/nix/gcroots/t3code-docker-runtime"
            )
            if gcroot.is_symlink():
                if os.readlink(gcroot) != spec["runtimePackage"]:
                    raise RuntimeError(
                        "existing engine GC root differs; review before replacing"
                    )
            else:
                gcroot.symlink_to(spec["runtimePackage"])
            run(
                "nix",
                "copy",
                "--no-check-sigs",
                "--to",
                "local?root=/srv/apps/t3code/nix-root",
                spec["runtimePackage"],
            )
            # Ownership is recorded before starting any unit, allowing cleanup
            # after a partial start with this exact reviewed specification.
            marker.write_text(json.dumps(spec))
            for path, text in files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            run("systemctl", "daemon-reload")
            run(
                "systemctl",
                "start",
                manager,
                "t3code-docker.socket",
                "t3code-docker-ports.socket",
            )
            print("Rootless candidate units started; production T3 unit untouched")
        finally:
            if identity() != before:
                raise RuntimeError(
                    "active T3 identity changed during candidate activation"
                )
            print("PASS active T3 and inner runtime identity preserved")


if __name__ == "__main__":
    main()
