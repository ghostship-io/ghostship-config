"""Supply the isolated manager's explicit, empty user-activation contract.

The manager cannot load ordinary host user units. Preserve that boundary while
letting NixOS restart its mandatory activation unit, including on older managers
whose immutable unit directory predates the declaration.
"""

import argparse
import subprocess


def reconcile(
    user, uid, systemctl, systemd_run, runuser, env, true, run=subprocess.run
):
    active = run([systemctl, "is-active", "--quiet", f"user@{uid}.service"])
    if active.returncode in (3, 4):
        return
    active.check_returncode()
    prefix = [
        runuser,
        "-u",
        user,
        "--",
        env,
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
    ]
    state = run(
        [
            *prefix,
            systemctl,
            "--user",
            "show",
            "nixos-activation.service",
            "--property=LoadState",
            "--value",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    if state.stdout.strip() == "loaded":
        return
    if state.stdout.strip() != "not-found":
        raise ValueError("unexpected isolated activation unit state")
    # Active RemainAfterExit transient units survive daemon reexec. Do not link
    # into ordinary user paths: this manager has a deliberately private unit path.
    run(
        [
            *prefix,
            systemd_run,
            "--user",
            "--unit=nixos-activation.service",
            "--description=Isolated Podman manager activation (no host user hooks)",
            "--property=Type=oneshot",
            "--property=RemainAfterExit=yes",
            true,
        ],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("user", "uid", "systemctl", "systemd-run", "runuser", "env", "true"):
        parser.add_argument(f"--{name}", required=True)
    reconcile(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
