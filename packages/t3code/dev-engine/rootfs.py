"""Assemble ONLY the dedicated Podman manager's disposable filesystem.

Runs as root during opt-in activation, never against the active T3 container.
All mounts are below a private /run directory. No ownership/ACL changes to source
trees are made. The service must be stopped before teardown.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path


def checked_source(path):
    source = Path(path)
    # NixOS's trusted wrapper directory is itself a generation symlink.
    if path in ("/run/wrappers/bin/newuidmap", "/run/wrappers/bin/newgidmap"):
        source = source.resolve(strict=True)
    if not source.is_absolute() or source.resolve() != source:
        raise ValueError(f"mount source must be absolute without symlinks: {path}")
    if not source.exists():
        raise ValueError(f"mount source does not exist: {path}")
    return source


def destination(root, path):
    relative = Path(path).relative_to("/")
    if ".." in relative.parts:
        raise ValueError(f"unsafe mount destination: {path}")
    target = root / relative
    # Refuse symlinks in the assembled tree, including the final component.
    for item in [target, *target.parents]:
        if item == root:
            break
        if item.is_symlink():
            raise ValueError(f"symlink in mount destination: {path}")
    return target


def run(*args):
    subprocess.run(args, check=True)


def assemble(root, spec):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.path.ismount(root):
        raise ValueError("sandbox already mounted; stop its manager and teardown first")
    run("mount", "-t", "tmpfs", "-o", "mode=0755,size=64M", "tmpfs", str(root))
    try:
        # ProtectProc implies MountAPIVFS. systemd overlays a non-mounted /run
        # with a fresh tmpfs, hiding our boot marker and private runtime sockets.
        # A separate empty tmpfs preserves these scoped mounts without exposing
        # the host's /run or weakening ProtectProc.
        (root / "run").mkdir()
        run(
            "mount",
            "-t",
            "tmpfs",
            "-o",
            "mode=0755,size=16M",
            "tmpfs",
            str(root / "run"),
        )
        for entry in spec["mounts"]:
            source = checked_source(entry["source"])
            target = destination(root, entry["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                target.mkdir(exist_ok=True)
            else:
                target.touch(exist_ok=True)
            # Nonrecursive bind deliberately excludes nested host mounts.
            options = (
                ["-o", f"X-mount.idmap={entry['idmap']}"] if "idmap" in entry else []
            )
            run("mount", "--bind", *options, str(source), str(target))
            if entry.get("readOnly", False):
                run("mount", "-o", "remount,bind,ro", str(target))
        # The coordinator seeds runtimePackage into T3's PRIVATE store. Never
        # mount the host store to paper over an incomplete image closure.
        for path in Path(spec["closure"]).read_text().splitlines():
            if not path.startswith("/nix/store/") or len(Path(path).parts) != 4:
                raise ValueError("invalid engine closure entry")
            if not destination(root, path).exists():
                raise ValueError(
                    f"seed t3codePodman.runtimePackage into the private T3 Nix store first: {path}"
                )
        # Read-only bind mounts still allow connecting to Unix sockets. Hide
        # the inner Nix daemon socket, rather than trusting read-only flags.
        daemon_socket = destination(root, "/nix/var/nix/daemon-socket")
        if not daemon_socket.is_dir() or daemon_socket.is_symlink():
            raise ValueError(
                "prepare the private Nix daemon-socket directory before assembly; refusing an unmasked future socket"
            )
        mask = root / ".nix-daemon-socket-mask"
        mask.mkdir(mode=0o000)
        run("mount", "--bind", str(mask), str(daemon_socket))
        for path, content in spec["files"].items():
            target = destination(root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        for path in spec["directories"]:
            destination(root, path).mkdir(parents=True, exist_ok=True)
        if not os.path.ismount(root / "tmp"):
            (root / "tmp").chmod(0o1777)
        (root / "var/tmp").chmod(0o1777)
    except BaseException:
        run("umount", "--recursive", str(root))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["start", "stop"])
    parser.add_argument("root", type=Path)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    if args.root != Path("/run/t3code-podman-rootfs"):
        parser.error("only /run/t3code-podman-rootfs may be managed")
    if args.operation == "start":
        if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
            parser.error("cgroup v2 is required")
        assemble(args.root, json.loads(args.spec.read_text()))
    elif os.path.ismount(args.root):
        run("umount", "--recursive", str(args.root))


if __name__ == "__main__":
    main()
