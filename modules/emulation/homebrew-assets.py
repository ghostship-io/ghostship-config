"""Snapshot regular homebrew assets without following package-supplied links."""

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path


def copy_tree(directory_fd, destination):
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if stat.S_ISDIR(info.st_mode):
            flags |= os.O_DIRECTORY
        elif not stat.S_ISREG(info.st_mode):
            raise ValueError("homebrew assets contain a symlink or special file")
        fd = os.open(name, flags, dir_fd=directory_fd)
        try:
            opened = os.fstat(fd)
            if stat.S_ISDIR(opened.st_mode):
                child = destination / name
                child.mkdir()
                copy_tree(fd, child)
            elif stat.S_ISREG(opened.st_mode):
                with os.fdopen(os.dup(fd), "rb") as source, (destination / name).open("xb") as target:
                    shutil.copyfileobj(source, target)
            else:
                raise ValueError("homebrew asset changed type during copy")
        finally:
            os.close(fd)


def snapshot(source, target):
    # An operator's existing ordinary SD-card data directory remains theirs.
    if target.exists() and not target.is_symlink():
        return False
    old = target.readlink() if target.is_symlink() else None
    destination = Path(tempfile.mkdtemp(prefix=".ghostship-assets-", dir=target.parent))
    try:
        fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            copy_tree(fd, destination)
        finally:
            os.close(fd)
        # Replace the link atomically; never traverse an existing target link.
        link = destination.with_name(destination.name + ".link")
        link.symlink_to(destination)
        link.replace(target)
    except BaseException:
        shutil.rmtree(destination)
        raise
    if old is not None and old.parent == target.parent and old.name.startswith(".ghostship-assets-"):
        # rmtree's fd-based implementation rejects substituted symlinks.
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
    return True


if __name__ == "__main__":
    try:
        snapshot(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError) as exc:
        # Detach any previously linked assets before a refused package launches.
        target = Path(sys.argv[2])
        if target.is_symlink():
            target.unlink()
        print(f"Unsafe homebrew assets refused: {exc}", file=sys.stderr)
        sys.exit(1)
