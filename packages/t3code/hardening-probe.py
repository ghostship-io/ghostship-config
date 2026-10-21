"""Boot a disposable, unprivileged T3 platform without touching live state.

Run as host root. Requires the committed ghostship-t3code learning profile.
This checks the platform only; it never claims authenticated provider acceptance.
"""

import argparse
import fcntl
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=180, **kwargs).strip()


def identity():
    container = json.loads(run("podman", "inspect", "t3code"))[0]
    return [
        container["Id"],
        container["State"]["StartedAt"],
        container["State"]["Pid"],
        run("systemctl", "show", "podman-t3code.service", "-p", "MainPID", "--value"),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="localhost/ghostship-t3code:t3code-runtime")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run on the host as root")
    with open("/run/t3code-hardening-probe.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = identity()
        systemctl = run(
            "podman",
            "run",
            "--rm",
            "--network=none",
            "--entrypoint=/bin/readlink",
            args.image,
            "-f",
            "/bin/systemctl",
        )
        systemd = str(Path(systemctl).parent.parent / "lib/systemd/systemd")
        with tempfile.TemporaryDirectory(
            prefix="t3code-probe-", dir="/var/tmp"
        ) as temporary:
            root = Path(temporary)
            for name in ("home", "workspace", "tmp"):
                (root / name).mkdir(mode=0o755)
                os.chown(root / name, 3000, 3000)
            (root / "tmp").chmod(0o1777)
            setup = root / "setup.service"
            setup.write_text(
                "[Service]\nType=oneshot\nExecStart=/bin/true\nRemainAfterExit=yes\n"
            )
            # basic.target does not start application services or updater timers.
            name = "t3code-hardening-probe"
            if (
                subprocess.run(
                    ["podman", "container", "exists", name], check=False
                ).returncode
                == 0
            ):
                raise RuntimeError(
                    "previous candidate exists; inspect it before retrying"
                )
            try:
                run(
                    "podman",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network=none",
                    "--systemd=always",
                    "--cap-add=SYS_RESOURCE",
                    "--memory=4g",
                    "--tty",
                    "--env=SYSTEMD_LOG_TARGET=console",
                    "--env=SYSTEMD_LOG_LEVEL=debug",
                    "--pids-limit=2048",
                    "--security-opt=apparmor=ghostship-t3code",
                    "-v",
                    f"{root / 'home'}:/home/t3code:rw",
                    "-v",
                    f"{root / 'workspace'}:/workspace:rw",
                    "-v",
                    f"{root / 'tmp'}:/tmp:rw",
                    "-v",
                    f"{setup}:/etc/systemd/system/t3code-container-setup.service:ro",
                    f"--entrypoint={systemd}",
                    args.image,
                    "--unit=basic.target",
                )

                def execute(*command, user="0:0"):
                    return run("podman", "exec", "--user", user, name, *command)

                for _ in range(60):
                    try:
                        execute("systemctl", "show", "--property=Version")
                        break
                    except subprocess.CalledProcessError:
                        state = json.loads(run("podman", "inspect", name))[0]["State"]
                        if not state["Running"]:
                            raise RuntimeError(f"candidate exited: {state['ExitCode']}")
                        time.sleep(1)
                execute("mkdir", "-p", "/run/user/3000")
                execute("chown", "3000:3000", "/run/user/3000")
                execute("chmod", "0700", "/run/user/3000")
                execute("systemctl", "start", "nix-daemon.service", "user@3000.service")
                checks = {
                    "systemd": execute(
                        "systemctl",
                        "is-active",
                        "nix-daemon.service",
                        "user@3000.service",
                    ),
                    "nix": execute(
                        "nix", "store", "ping", "--store", "daemon", user="3000:3000"
                    ),
                    "user_service": execute(
                        "env",
                        "XDG_RUNTIME_DIR=/run/user/3000",
                        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus",
                        "systemd-run",
                        "--user",
                        "--wait",
                        "--pipe",
                        "/bin/true",
                        user="3000:3000",
                    ),
                    "sandbox": execute(
                        "bwrap",
                        "--unshare-user",
                        "--unshare-pid",
                        "--dev-bind",
                        "/",
                        "/",
                        "--proc",
                        "/proc",
                        "/bin/true",
                        user="3000:3000",
                    ),
                }
                inspected = json.loads(run("podman", "inspect", name))[0]
                assert not inspected["HostConfig"]["Privileged"]
                checks["privileged"] = False
                checks["capabilities"] = inspected["EffectiveCaps"]
                print(json.dumps(checks, indent=2))
            finally:
                subprocess.run(["podman", "logs", "--tail=30", name], check=False)
                subprocess.run(["podman", "rm", "-f", "--time=10", name], check=False)
                after = identity()
                if after != before:
                    raise RuntimeError(
                        f"active T3 identity changed: {before} -> {after}"
                    )
                print("PASS active T3 container, start time and service PID preserved")


if __name__ == "__main__":
    main()
