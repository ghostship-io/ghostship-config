#!/usr/bin/env python3
"""Identify the managed launcher chains and their immutable Nix closures."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import shlex


SAFE_PART = re.compile(r"[A-Za-z0-9._-]{1,64}")


def launcher_key(home, container_home):
    home = Path(home)
    container_home = PurePosixPath(container_home)
    digest = hashlib.sha256()
    for tool in ("agent", "ghostship", "ghostship-bladebro"):
        current = home / ".local/state/t3code-shared-agents/bin" / tool
        seen = set()
        digest.update((tool + "\0").encode())
        for _ in range(4):
            if current in seen or current.is_symlink() or not current.is_file():
                raise ValueError("managed launcher missing, cyclic or a symlink")
            seen.add(current)
            content = current.read_bytes()
            digest.update(hashlib.sha256(content).digest())
            text = content.decode("utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if (stripped and not stripped.startswith("#") and not line.startswith("exec ")
                        and stripped not in ("unset LD_LIBRARY_PATH", "set -e", "set -eu", "set -euo pipefail")):
                    raise ValueError("managed launcher contains untracked commands")
            commands = [line for line in text.splitlines() if line.startswith("exec ")]
            try:
                argv = shlex.split(commands[0][len("exec "):]) if len(commands) == 1 else []
            except ValueError:
                argv = []
            if len(argv) != 2 or argv[1] != "$@":
                raise ValueError("managed launcher has no proven immutable store identity")
            target = PurePosixPath(argv[0])
            try:
                relative = target.relative_to(container_home)
            except ValueError:
                relative = None
            if relative is not None:
                if (len(relative.parts) < 4 or relative.parts[:3] != (".local", "state", "ghostship")
                        or any(part in (".", "..") or not SAFE_PART.fullmatch(part) for part in relative.parts)):
                    raise ValueError("managed launcher points outside its managed tree")
                current = home.joinpath(*relative.parts)
                continue
            if (not target.is_absolute() or target.parts[:3] != ("/", "nix", "store")
                    or len(target.parts) < 5
                    or not re.fullmatch(r"[0-9a-z]{32}-[A-Za-z0-9._+-]+", target.parts[3])
                    or any(part in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._+-]+", part)
                           for part in target.parts[4:])):
                raise ValueError("managed launcher has no immutable store identity")
            # The Nix output path identifies its closure, including the source
            # root and imported modules; it is already present in the digest.
            break
        else:
            raise ValueError("managed launcher chain is too deep")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--container-home", required=True)
    args = parser.parse_args()
    try:
        print(launcher_key(args.home, args.container_home))
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"cannot identify managed launcher inputs: {error}\n")


if __name__ == "__main__":
    main()
