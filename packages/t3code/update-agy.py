"""Install the official Antigravity terminal CLI in the persistent user home."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

BASE = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app"


def main():
    arch = {"aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
    with urllib.request.urlopen(
        f"{BASE}/manifests/linux_{arch}.json", timeout=60
    ) as response:
        release = json.load(response)
    url = release["url"]
    if not url.startswith(
        "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
    ):
        raise ValueError("Unexpected Antigravity CLI download URL")
    target = Path.home() / ".local/bin/agy"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            installed = subprocess.check_output(
                [target, "--version"], text=True, timeout=30
            ).strip()
        except (OSError, subprocess.SubprocessError):
            # A broken installed copy must not block a verified replacement.
            installed = None
        if installed == release["version"]:
            print(f"agy {installed} is current")
            return
    # Stage on the same filesystem so replacement is atomic, including during self-update.
    with tempfile.TemporaryDirectory(
        prefix=".agy-update-", dir=target.parent
    ) as temporary:
        stage = Path(temporary)
        archive = stage / "release.tar.gz"
        with (
            urllib.request.urlopen(url, timeout=60) as source,
            archive.open("wb") as output,
        ):
            shutil.copyfileobj(source, output)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha512").hexdigest()
        if digest != release["sha512"]:
            raise ValueError("Antigravity CLI checksum mismatch")
        binary = stage / "agy"
        with tarfile.open(archive) as package:
            member = package.getmember("antigravity")
            if not member.isfile():
                raise ValueError("Expected a regular Antigravity CLI binary")
            with package.extractfile(member) as source, binary.open("wb") as output:
                shutil.copyfileobj(source, output)
        binary.chmod(0o755)
        version = subprocess.check_output(
            [binary, "--version"], text=True, timeout=30
        ).strip()
        if version != release["version"]:
            raise ValueError("Antigravity CLI version probe failed")
        os.replace(binary, target)
        print(f"Installed agy {version}")


def install_hooks():
    root = Path.home() / ".t3code-container"
    root.mkdir(parents=True, exist_ok=True)
    script = root / "update-agy.py"
    if Path(__file__).resolve() != script.resolve():
        shutil.copyfile(__file__, script)
    for phase in ("bootstrap.d", "after-update.d"):
        hook = root / "hooks" / phase / "45-agy-cli-update"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            '#!/bin/sh\nexec python3 "$HOME/.t3code-container/update-agy.py" --update\n'
        )
        hook.chmod(0o755)


if __name__ == "__main__":
    main()
    if "--update" not in sys.argv[1:]:
        install_hooks()
