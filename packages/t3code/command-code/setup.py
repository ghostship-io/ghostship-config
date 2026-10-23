"""Install the reviewed Command Code distribution before T3 starts."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = "1.88.0"
INTEGRITY = "sha512-8es7pmDlw1YYbUYUW3RHDGyI3zBQAhvkZaBh2ZxSnuuzZY1mavrN4e5+SICi8nBqah6GYThMLtvfqmFnL95i3A=="
FILES = ("package.json", "package-lock.json", "acp.py", "paid-models.json", "provider.json")


def validate_lock(root):
    package = json.loads((root / "package.json").read_text())
    lock = json.loads((root / "package-lock.json").read_text())
    entry = lock["packages"]["node_modules/command-code"]
    if package["dependencies"] != {"command-code": VERSION} or entry["version"] != VERSION:
        raise ValueError("Command Code version must match the reviewed pin")
    if entry["integrity"] != INTEGRITY:
        raise ValueError("Command Code integrity must match the reviewed pin")
    for name, item in lock["packages"].items():
        if name and (not item.get("integrity", "").startswith("sha512-")
                     or not item.get("resolved", "").startswith("https://registry.npmjs.org/")):
            raise ValueError("unverified dependency in Command Code lock")


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".command-code-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def configure(home, source):
    # Called by ExecStartPre, before the server reads settings. Never edit live.
    path = home / ".t3/userdata/settings.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    instances = data.setdefault("providerInstances", {})
    old = instances.get("commandCode", {})
    if old and old.get("driver") != "acpRegistry":
        raise ValueError("commandCode instance already belongs to another driver")
    provider = json.loads((source / "provider.json").read_text())
    provider["config"]["commandPath"] = str(home / ".local/bin/cmd")
    instances["commandCode"] = provider
    if not path.exists() or json.loads(path.read_text()) != data:
        atomic_json(path, data)


def install(home, source=ROOT):
    validate_lock(source)
    node = subprocess.run(["node", "--version"], check=True, capture_output=True, text=True)
    if int(node.stdout.strip().lstrip("v").split(".")[0]) < 22:
        raise ValueError("Command Code requires Node >=22")
    fingerprint = hashlib.sha256(b"".join((source / f).read_bytes() for f in FILES)).hexdigest()
    base = home / ".local/share/t3code-tools/command-code"
    release = base / fingerprint
    ready = release / ".ready"
    if not ready.exists():
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=base) as temporary:
            stage = Path(temporary)
            for file in FILES:
                shutil.copyfile(source / file, stage / file)
            # npm sees no externally injected provider credentials. It verifies
            # every tarball against the committed lock, including the root CLI.
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("BW_", "COMMAND_CODE_", "AGENT_BW_"))}
            subprocess.run(["npm", "ci", "--prefix", str(stage), "--ignore-scripts",
                            "--no-audit", "--no-fund"], env=env, check=True, timeout=180,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            installed = json.loads((stage / "node_modules/command-code/package.json").read_text())
            if installed["version"] != VERSION:
                raise ValueError("installed Command Code version mismatch")
            (stage / "acp.py").chmod(0o755)
            (stage / ".ready").touch()
            if release.exists():
                shutil.rmtree(release)
            stage.rename(release)
            stage.mkdir()  # TemporaryDirectory can clean its original pathname.
    target = home / ".local/bin/cmd"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not target.is_symlink() or not target.resolve().is_relative_to(base)):
        raise ValueError("refusing to replace an unmanaged cmd")
    temporary = target.with_name(".cmd-install")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release / "acp.py")
    os.replace(temporary, target)
    configure(home, source)


if __name__ == "__main__":
    install(Path.home())
