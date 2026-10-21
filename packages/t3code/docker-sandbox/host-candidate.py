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


def owned_directory(path, uid, gid, *, parent_fd=None, mode=0o700):
    """Open a real directory without following a daemon-controlled symlink."""
    created = False
    try:
        os.mkdir(path, mode, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not created and (info.st_uid, info.st_gid) != (uid, gid):
            raise RuntimeError(f"unexpected existing directory ownership: {path}")
        if created:
            os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        return fd
    except BaseException:
        os.close(fd)
        raise


def manager_active(manager):
    return run("systemctl", "show", manager, "-p", "ActiveState", "--value") not in (
        "inactive",
        "failed",
    )


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
    if (
        spec["user"] != "t3code-docker"
        or spec["uid"] != 62040
        or spec["state"] != "/var/lib/t3code-docker"
    ):
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
                for path, text in files.items():
                    if path.is_symlink() or (
                        path.exists() and path.read_text() != text
                    ):
                        raise RuntimeError(f"candidate unit ownership changed: {path}")
                if manager_active(manager):
                    dropins = run(
                        "systemctl", "show", manager, "-p", "DropInPaths", "--value"
                    ).split()
                    expected = (
                        "/run/systemd/system/user@62040.service.d/50-t3-candidate.conf"
                    )
                    if (
                        expected not in dropins
                        or run(
                            "systemctl",
                            "show",
                            manager,
                            "-p",
                            "RootDirectory",
                            "--value",
                        )
                        != "/run/t3code-docker-rootfs"
                    ):
                        raise RuntimeError(
                            "active manager is not the installed candidate; leaving it intact"
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
                gcroot = Path(
                    "/srv/apps/t3code/nix-root/nix/var/nix/gcroots/t3code-docker-runtime"
                )
                if (
                    gcroot.is_symlink()
                    and os.readlink(gcroot) == spec["runtimePackage"]
                ):
                    gcroot.unlink()
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
            if manager_active(manager):
                raise RuntimeError(
                    "an existing user manager is running; leaving it intact"
                )
            for directory in (
                "/etc/systemd/system/user@62040.service.d",
                "/run/systemd/system/user@62040.service.d",
            ):
                if Path(directory).exists() and any(Path(directory).iterdir()):
                    raise RuntimeError(
                        f"existing manager drop-ins require review: {directory}"
                    )
            for path in files:
                if (
                    path.exists()
                    or path.is_symlink()
                    or (Path("/etc/systemd/system") / path.name).exists()
                ):
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
            state_fd = owned_directory(spec["state"], spec["uid"], spec["uid"])
            try:
                home_fd = owned_directory(
                    "home", spec["uid"], spec["uid"], parent_fd=state_fd
                )
                os.close(home_fd)
            finally:
                os.close(state_fd)
            socket_fd = owned_directory(
                "/run/t3code-docker", 0, grp.getgrnam("apps").gr_gid, mode=0o750
            )
            os.close(socket_fd)
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
