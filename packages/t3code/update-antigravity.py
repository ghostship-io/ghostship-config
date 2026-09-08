"""Stage official ACP releases and publish only after an offline protocol probe."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REGISTRY = "https://raw.githubusercontent.com/agentclientprotocol/registry/main/antigravity-acp/agent.json"
BINARIES = ("agy_acp_server.par", "localharness_external")


def release_info(metadata):
    version = metadata["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid Antigravity release version")
    url = metadata["distribution"]["binary"]["linux-x86_64"]["archive"]
    expected = (
        "https://dl.google.com/agy-extensions/releases/linux/"
        f"agy-acp-server-agy_acp_server_{version}-linux-x86_64.zip"
    )
    if url != expected:
        raise ValueError("Unexpected Antigravity release URL")
    return version, url


def download(url, destination):
    with (
        urllib.request.urlopen(url, timeout=60) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)


def probe_runtime(directory, probe):
    subprocess.run(
        [sys.executable, str(probe)],
        env=dict(os.environ, T3CODE_ANTIGRAVITY_RUNTIME=str(directory)),
        check=True,
        timeout=60,
    )


def update(root, bundled_version, metadata, probe, fetch=download, check=probe_runtime):
    version, url = release_info(metadata)
    root.mkdir(parents=True, exist_ok=True)
    current = root / "current"
    installed_version = bundled_version
    if current.is_dir():
        installed_version = json.loads((current / "release.json").read_text())[
            "version"
        ]
    if tuple(map(int, version.split("."))) <= tuple(
        map(int, installed_version.split("."))
    ):
        print(f"Antigravity {installed_version} is current")
        return False

    releases = root / "releases"
    releases.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".staging-", dir=root) as temporary:
        stage = Path(temporary)
        archive = stage / "release.zip"
        fetch(url, archive)
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        runtime = stage / "runtime"
        runtime.mkdir()
        # Extract only the two expected binaries; never trust archive paths.
        with zipfile.ZipFile(archive) as package:
            for name in BINARIES:
                with package.open(name) as source, (runtime / name).open("wb") as dest:
                    shutil.copyfileobj(source, dest)
                (runtime / name).chmod(0o755)
        check(runtime, probe)
        (runtime / "release.json").write_text(
            json.dumps({"version": version, "url": url, "sha256": digest}) + "\n"
        )
        destination = releases / f"{version}-{digest}"
        if not destination.exists():
            runtime.rename(destination)
        link = stage / "current"
        link.symlink_to(destination)
        # Server and helper switch together; failed checks leave current intact.
        link.replace(current)
    print(f"Activated Antigravity {version} (sha256 {digest})")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundled-version", required=True)
    parser.add_argument("--probe", required=True, type=Path)
    args = parser.parse_args()
    root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    root /= "t3code-tools/antigravity"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "update.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with urllib.request.urlopen(REGISTRY, timeout=30) as response:
            metadata = json.load(response)
        update(root, args.bundled_version, metadata, args.probe)


if __name__ == "__main__":
    main()
