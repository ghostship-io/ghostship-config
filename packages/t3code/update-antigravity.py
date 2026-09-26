"""Stage official ACP releases and publish only after an offline protocol probe."""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REGISTRY = "https://raw.githubusercontent.com/agentclientprotocol/registry/main/antigravity-acp/agent.json"
ARCHIVE_URL_PATTERN = (
    r"^https://dl\.google\.com/agy-extensions/releases/linux/"
    r"agy-acp-server-(?:agy_acp_server_)?{version}-linux-{arch}\.zip$"
)


def _valid_archive_url(url, version, arch):
    escaped_version = re.escape(version)
    escaped_arch = re.escape(arch)
    pattern = ARCHIVE_URL_PATTERN.format(
        version=escaped_version, arch=escaped_arch
    )
    return bool(re.fullmatch(pattern, url))


def release_info(metadata, machine=None):
    """Resolve the release version and the archives to stage.

    The ACP server must stay on x86_64 because Google's binary aborts on hosts
    with 16 KiB pages. The harness is a static Go binary that runs natively, so
    an ARM64 host stages the matching ARM64 harness instead of emulating it.
    """
    version = metadata["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid Antigravity release version")
    machine = platform.machine() if machine is None else machine
    harness_arch = "arm64" if machine in ("aarch64", "arm64") else "x86_64"
    server = metadata["distribution"]["binary"]["linux-x86_64"]["archive"]
    harness = metadata["distribution"]["binary"][
        "linux-aarch64" if harness_arch == "arm64" else "linux-x86_64"
    ]["archive"]
    if not _valid_archive_url(server, version, "x86_64") or not _valid_archive_url(
        harness, version, harness_arch
    ):
        raise ValueError("Unexpected Antigravity release URL")
    return version, {"agy_acp_server.par": server, "localharness_external": harness}


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


def update(
    root,
    bundled_version,
    metadata,
    probe,
    fetch=download,
    check=probe_runtime,
    machine=None,
):
    version, archives = release_info(metadata, machine)
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
        runtime = stage / "runtime"
        runtime.mkdir()
        digests = {}
        # Extract only the two expected binaries; never trust archive paths.
        for name, url in archives.items():
            archive = stage / f"{name}.zip"
            fetch(url, archive)
            with archive.open("rb") as stream:
                digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            with zipfile.ZipFile(archive) as package:
                with package.open(name) as source, (runtime / name).open("wb") as dest:
                    shutil.copyfileobj(source, dest)
            (runtime / name).chmod(0o755)
        check(runtime, probe)
        (runtime / "release.json").write_text(
            json.dumps(
                {"version": version, "archives": archives, "sha256": digests}
            )
            + "\n"
        )
        destination = releases / f"{version}-{digests['agy_acp_server.par']}"
        if not destination.exists():
            runtime.rename(destination)
        link = stage / "current"
        link.symlink_to(destination)
        # Server and helper switch together; failed checks leave current intact.
        link.replace(current)
    print(
        f"Activated Antigravity {version} "
        f"(server sha256 {digests['agy_acp_server.par']})"
    )
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
