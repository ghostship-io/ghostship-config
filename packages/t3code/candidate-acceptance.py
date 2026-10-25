"""Accept a new T3 image in disposable candidate storage before pickup."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

_probe_spec = importlib.util.spec_from_file_location(
    "t3code_hardening_probe", Path(__file__).with_name("hardening-probe.py")
)
_probe = importlib.util.module_from_spec(_probe_spec)
_probe_spec.loader.exec_module(_probe)

CHECKS = ("authenticated_app", "provider_turn", "agent_cli", "skills", "desktop_transport")


def candidate_name(deployment_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", deployment_id):
        raise ValueError("invalid T3 candidate deployment identifier")
    return f"t3code-candidate-{deployment_id}"


def image_details(image_archive):
    with tarfile_open(image_archive) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))[0]
        config = archive.extractfile(manifest["Config"]).read()
        tags = manifest.get("RepoTags") or []
    if not tags:
        raise RuntimeError("candidate image archive has no repository tag")
    return hashlib.sha256(config).hexdigest(), tags[0]


def tarfile_open(path):
    import tarfile
    return tarfile.open(path)


def command(engine, *args, timeout=180):
    return subprocess.run(
        [*engine, *args], check=False, text=True, capture_output=True, timeout=timeout
    )


def assert_ok(engine, *args, timeout=180):
    result = command(engine, *args, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"candidate command failed: {args[0]}")
    return result.stdout.strip()


def check_candidate(engine, name, timeout_s=300):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if command(engine, "exec", name, "curl", "-fsS", "--max-time", "5",
                   "http://127.0.0.1:3773/").returncode == 0:
            break
        state = command(engine, "inspect", name, "--format", "{{.State.Running}}")
        if state.returncode or state.stdout.strip() != "true":
            raise RuntimeError("candidate container exited before app readiness")
        time.sleep(2)
    else:
        raise RuntimeError("candidate app did not become ready")

    checks = {}
    checks["authenticated_app"] = command(
        engine, "exec", name, "curl", "-fsS", "--max-time", "10",
        "http://127.0.0.1:3773/"
    ).returncode == 0

    pick = command(engine, "exec", name, "agent", "models", "pick", "--role", "worker", "--json")
    route = ""
    if pick.returncode == 0:
        try:
            payload = json.loads(pick.stdout)
            selection = payload.get("data", {}).get("pick") or {}
            route = "/".join((selection.get("provider", ""), selection.get("model", "")))
        except (ValueError, AttributeError):
            route = ""
    checks["provider_turn"] = bool(route) and command(
        engine, "exec", name, "agent", "models", "prove", route, "--wait", "240", "--json",
        timeout=270
    ).returncode == 0
    checks["agent_cli"] = command(engine, "exec", name, "agent", "--help").returncode == 0
    checks["skills"] = command(engine, "exec", name, "agent", "skills", "doctor", "--json").returncode == 0
    checks["desktop_transport"] = command(
        engine, "exec", name, "agent", "tools", "doctor", "--json", "--only", "ghostship-bladebro"
    ).returncode == 0
    return checks


def accept(state_dir, image_archive, podman_bin, candidate_socket, home_dir,
           environment_files=(), volumes=(), systemctl_bin="systemctl",
           command_fn=command, identity_fn=None, candidate_uid=None):
    """Boot, check, record and remove one candidate without changing production."""
    identity_fn = identity_fn or _probe.identity
    candidate_uid = os.getuid() if candidate_uid is None else int(candidate_uid)
    state_dir = Path(state_dir)
    desired = (state_dir / "desired").read_text().strip()
    image_id, image_tag = image_details(image_archive)
    name = candidate_name(desired)
    receipts = state_dir / "receipts"
    receipt_path = receipts / f"{desired}.json"
    receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_path.unlink(missing_ok=True)
    before = identity_fn()
    engine = [podman_bin, "--remote", "--url", f"unix://{candidate_socket}"]
    candidate_home_root = state_dir / "candidate-home"
    candidate_home_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    home_copy = Path(tempfile.mkdtemp(prefix="t3code-candidate-home-",
                                      dir=candidate_home_root))
    created = False
    manager_started = False
    checks = {}
    try:
        subprocess.run(["cp", "-a", "--reflink=auto", f"{Path(home_dir)}/.", str(home_copy)],
                       check=True, timeout=300)
        for path in (home_copy, *home_copy.rglob("*")):
            if not path.is_symlink():
                os.chown(path, candidate_uid, candidate_uid)
        subprocess.run([systemctl_bin, "start", "t3code-podman-candidate.service"],
                       check=True, timeout=30)
        manager_started = True
        assert_ok(engine, "load", "--input", str(image_archive), timeout=300)
        volumes = list(volumes) + [f"{home_copy}:/home/t3code:rw"]
        args = ["run", "--detach", "--name", name, "--hostname", name,
                "--userns=keep-id:uid=3000,gid=3000",
                "--systemd=always", "--cap-drop=ALL", "--security-opt=unmask=/proc/*",
                "--pids-limit=2048", "--network=slirp4netns"]
        caps = json.loads(Path(__file__).with_name("runtime-caps.json").read_text())
        for cap in caps:
            args.extend(("--cap-add", cap))
        for item in environment_files:
            args.extend(("--env-file", str(item)))
        for item in volumes:
            args.extend(("--volume", str(item)))
        args.extend(("--volume", f"{candidate_socket}:/var/run/podman/podman.sock:rw"))
        created = True
        args.extend((image_tag, "--unit=multi-user.target"))
        assert_ok(engine, *args, timeout=300)
        checks = check_candidate(engine, name)
        after = identity_fn()
        if before != after:
            raise RuntimeError("production T3 identity changed during candidate acceptance")
        if any(checks.get(key) is not True for key in CHECKS):
            raise RuntimeError("candidate acceptance failed; receipt not written")
        receipt = {
            "deployment_id": desired,
            "image_id": image_id,
            "candidate_name": name,
            "live_before": before,
            "live_after": after,
            "checks": checks,
        }
        temporary = receipt_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, receipt_path)
        return receipt
    finally:
        if created:
            removed = command_fn(engine, "rm", "--force", "--time", "10", name, timeout=30)
            if removed.returncode:
                receipt_path.unlink(missing_ok=True)
                raise RuntimeError("candidate container teardown failed")
        if manager_started:
            subprocess.run([systemctl_bin, "stop", "t3code-podman-candidate.service"],
                           check=True, timeout=30)
        shutil.rmtree(home_copy, ignore_errors=True)
        after = identity_fn()
        if before != after:
            receipt_path.unlink(missing_ok=True)
            raise RuntimeError("production T3 identity changed during candidate teardown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--image-archive", required=True)
    parser.add_argument("--podman-bin", default="podman")
    parser.add_argument("--candidate-socket", default="/run/t3code-podman-candidate/podman.sock")
    parser.add_argument("--home-dir", required=True)
    parser.add_argument("--environment-file", action="append", default=[])
    parser.add_argument("--volume", action="append", default=[])
    parser.add_argument("--systemctl-bin", default="systemctl")
    parser.add_argument("--candidate-uid", type=int, required=True)
    args = parser.parse_args()
    accept(args.state_dir, args.image_archive, args.podman_bin, args.candidate_socket,
           args.home_dir, args.environment_file, args.volume, args.systemctl_bin,
           candidate_uid=args.candidate_uid)


if __name__ == "__main__":
    main()
