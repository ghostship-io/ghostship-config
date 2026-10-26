"""Keep the isolated manager's unit directory inside its private Nix store.

The manager loads units from the ``SYSTEMD_UNIT_PATH`` it captured when it
started, and that path is a per-generation store directory. Rootfs assembly
seeds the private store only when the rootfs unit starts, so a manager that
restarts on a later generation points at a directory its own ``RootDirectory``
does not contain: every unit reads ``not-found``, and
``switch-to-configuration``'s mandatory per-user ``nixos-activation.service``
restart fails, ending the switch with exit 4.

Seed and pin each directory the running manager can load from. This changes no
mount, unit definition or process: it only makes the manager's own unit
directory readable inside the root it already runs in.
"""

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path("/run/t3code-podman-rootfs")
GCROOT_PREFIX = "t3code-podman-manager-units-"


def unit_dirs(service, systemctl, run=subprocess.run, read_bytes=Path.read_bytes):
    """Unit directories named in the running manager's own environment."""
    result = run(
        [systemctl, "show", "--property=MainPID", "--value", service],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot read the state of {service}")
    pid = result.stdout.strip()
    if not pid.isdigit():
        raise ValueError(f"unreadable MainPID for {service}")
    if pid == "0":
        # Not running: the next start reads its own environment and is seeded
        # by rootfs assembly.
        return []
    try:
        environ = read_bytes(Path("/proc") / pid / "environ")
    except FileNotFoundError:
        return []
    paths = []
    for entry in environ.split(b"\0"):
        key, separator, value = entry.partition(b"=")
        if separator and key == b"SYSTEMD_UNIT_PATH":
            paths.extend(part for part in value.decode().split(":") if part)
    return paths


def seed(root, directories, store_root, gcroot, nix, nix_store, run=subprocess.run):
    """Copy missing unit directories from the host store into the private one."""
    root = Path(root)
    store_root = Path(store_root)
    gcroot = Path(gcroot)
    keep = set()
    for directory in dict.fromkeys(directories):
        source = Path(directory)
        if not source.is_absolute() or ".." in source.parts:
            raise ValueError(f"unsafe unit directory: {directory}")
        keep.add(f"{GCROOT_PREFIX}{source.name}")
        destination = root / source.relative_to("/")
        if destination.is_dir():
            continue
        if not source.is_dir():
            raise ValueError(f"unit directory is absent from the host store: {directory}")
        run(
            [nix, "copy", "--no-check-sigs", "--to", f"local?root={store_root}", str(source)],
            check=True,
        )
        run(
            [
                nix_store,
                "--store",
                f"local?root={store_root}",
                "--add-root",
                str(gcroot / f"{GCROOT_PREFIX}{source.name}"),
                "--realise",
                str(source),
            ],
            check=True,
        )
        if not destination.is_dir():
            raise ValueError(
                f"unit directory is still absent from the private store: {directory}"
            )
    # Only after the live set is pinned: retire this helper's roots for
    # generations no running manager or current generation reads any more, so
    # their runtime closures stop pinning the private store.
    prune_roots(gcroot, keep)


def prune_roots(gcroot, keep):
    """Drop this helper's GC roots for unit directories outside the live set."""
    try:
        entries = list(Path(gcroot).iterdir())
    except FileNotFoundError:
        return
    for entry in entries:
        if entry.name.startswith(GCROOT_PREFIX) and entry.name not in keep:
            # is_symlink() uses lstat(), so a root whose target is already
            # gone is still retired.
            if entry.is_symlink():
                entry.unlink()


def reconcile(root, service, current, store_root, gcroot, systemctl, nix, nix_store, run=subprocess.run):
    """Make every directory the manager loads units from present in its root."""
    if not os.path.ismount(root):
        # Assembly seeds the private store and the manager reads its mount then.
        return
    seed(
        root,
        [*unit_dirs(service, systemctl, run=run), str(current)],
        store_root,
        gcroot,
        nix,
        nix_store,
        run=run,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manager", required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--gcroot", type=Path, required=True)
    parser.add_argument("--systemctl", required=True)
    parser.add_argument("--nix", required=True)
    parser.add_argument("--nix-store", required=True)
    args = parser.parse_args()
    if args.root != ROOT:
        parser.error(f"only {ROOT} may be managed")
    reconcile(
        args.root,
        args.manager,
        args.current,
        args.store_root,
        args.gcroot,
        args.systemctl,
        args.nix,
        args.nix_store,
    )


if __name__ == "__main__":
    main()
