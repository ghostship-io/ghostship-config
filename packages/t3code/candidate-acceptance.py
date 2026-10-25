"""Accept a new T3 image in disposable candidate storage before pickup."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time

_probe_spec = importlib.util.spec_from_file_location(
    "t3code_hardening_probe", Path(__file__).with_name("hardening-probe.py")
)
_probe = importlib.util.module_from_spec(_probe_spec)
_probe_spec.loader.exec_module(_probe)

CHECKS = ("app_ready", "provider_turn", "agent_cli", "skills", "desktop_transport")
HOME_DIRS = (".agents/skills",)
PROVIDER_ENV = (
    "GOOGLE_GENERATIVE_AI_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN", "COHERE_API_KEY",
    "COMMAND_CODE_API_KEY", "AI_GATEWAY_API_KEY", "OLLAMA_API_KEY", "OPENROUTER_API_KEY",
    "KILO_API_KEY", "REQUESTY_API_KEY", "ORCAROUTER_API_KEY", "INCEPTION_API_KEY",
    "MISTRAL_API_KEY", "UPSTAGE_API_KEY", "ZHIPU_API_KEY", "POOLSIDE_API_KEY",
    "AGENT_DESKTOP_API_TOKEN",
)
API_KEY_ROUTE_ENV = {
    "google": "GOOGLE_GENERATIVE_AI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
ALLOWED_CANDIDATE_MOUNTS = {
    "/etc/ghostship/route-policy.json": "/etc/ghostship/route-policy.json",
    "/etc/ghostship/approved-free-workers.json": "/etc/ghostship/approved-free-workers.json",
    "/nix/store": "/nix/store",
}


def stage_candidate_inputs(source_home, candidate_home, candidate_inputs, candidate_uid,
                           tooling_path=None):
    """Stage a fresh HOME plus a read-only tree with only provider/agent inputs."""
    source_home = Path(source_home)
    candidate_home = Path(candidate_home)
    candidate_inputs = Path(candidate_inputs)
    candidate_home.mkdir(mode=0o700)
    candidate_inputs.mkdir(mode=0o700)
    for relative in HOME_DIRS:
        source = source_home / relative
        if not source.is_dir() or source.is_symlink():
            continue
        target = candidate_inputs / relative
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        for current, directories, files in os.walk(source, followlinks=False):
            current_path = Path(current)
            target_dir = target / current_path.relative_to(source)
            target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            directories[:] = [name for name in directories if not (current_path / name).is_symlink()]
            for name in files:
                item = current_path / name
                if item.is_symlink() or not item.is_file():
                    continue
                copied = target_dir / name
                shutil.copyfile(item, copied)
                copied.chmod(0o444)
    for relative in HOME_DIRS:
        if (candidate_inputs / relative).exists():
            link = candidate_home / relative
            link.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            link.symlink_to(Path("/run/t3code-candidate-inputs") / relative)
    if tooling_path:
        managed = candidate_home / ".local/state/ghostship-t3-tools/current"
        managed.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        managed.symlink_to(tooling_path)
    for path in (candidate_home, candidate_inputs, *candidate_home.rglob("*"),
                 *candidate_inputs.rglob("*")):
        if not path.is_symlink():
            os.chown(path, candidate_uid, candidate_uid)


def write_provider_env(source_file, target_file):
    """Copy only provider/desktop keys; never forward GitHub or Bitwarden secrets."""
    values = {}
    if source_file and Path(source_file).is_file():
        for raw_line in Path(source_file).read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, raw = line.split("=", 1)
            key, raw = key.strip(), raw.strip()
            if key not in PROVIDER_ENV:
                continue
            if raw.startswith(("'", '"')):
                parsed = shlex.split(raw, comments=False)
                if len(parsed) != 1:
                    raise ValueError(f"invalid quoting in candidate provider value {key}")
                raw = parsed[0]
            if not raw:
                continue
            if any(char in raw for char in ("\n", "\r", "\x00")):
                raise ValueError(f"unsupported multiline candidate provider value {key}")
            values[key] = raw
    target_file = Path(target_file)
    target_file.write_text("".join(f"{key}={values[key]}\n" for key in PROVIDER_ENV if key in values))
    target_file.chmod(0o400)
    return target_file


def write_candidate_systemd_overrides(candidate_tmp):
    """Keep container setup, but skip home hooks/bootstrap that can run automation."""
    overrides = Path(candidate_tmp) / "systemd-overrides"
    server_dir = overrides / "t3code-server.service.d"
    bootstrap_dir = overrides / "t3code-bootstrap.service.d"
    server_dir.mkdir(parents=True)
    bootstrap_dir.mkdir(parents=True)
    (server_dir / "10-candidate.conf").write_text(
        "[Service]\nExecStartPre=\nExecStartPost=\n"
    )
    (bootstrap_dir / "10-candidate.conf").write_text(
        "[Service]\nExecStart=\nExecStart=/bin/true\n"
    )
    for path in (overrides, server_dir, bootstrap_dir,
                 server_dir / "10-candidate.conf", bootstrap_dir / "10-candidate.conf"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    return server_dir, bootstrap_dir


def remove_candidate_workspace(path):
    path = Path(path)
    if not path.exists():
        return
    for item in (path, *path.rglob("*")):
        if item.is_symlink():
            continue
        item.chmod(0o700 if item.is_dir() else 0o600)
    shutil.rmtree(path)


def validate_candidate_mounts(volumes):
    for volume in volumes:
        parts = str(volume).split(":", 2)
        if len(parts) != 3:
            raise ValueError("candidate mounts must specify source, target and read-only mode")
        source, target, mode = parts
        if ALLOWED_CANDIDATE_MOUNTS.get(source) != target or mode != "ro":
            raise ValueError("candidate mount is outside the read-only acceptance allowlist")
    return list(volumes)


def candidate_name(deployment_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", deployment_id):
        raise ValueError("invalid T3 candidate deployment identifier")
    return f"t3code-candidate-{deployment_id}"


def image_details(image_archive):
    with tarfile_open(image_archive) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))[0]
        config_bytes = archive.extractfile(manifest["Config"]).read()
        config = json.loads(config_bytes)
        tags = manifest.get("RepoTags") or []
    if not tags:
        raise RuntimeError("candidate image archive has no repository tag")
    container_config = config.get("config") or {}
    entrypoint = container_config.get("Entrypoint")
    if (not isinstance(entrypoint, list) or not entrypoint
            or not isinstance(entrypoint[0], str)
            or Path(entrypoint[0]).name != "systemd"):
        raise RuntimeError("candidate image archive requires a systemd entrypoint")
    return hashlib.sha256(config_bytes).hexdigest(), tags[0]


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


def check_candidate(engine, name, provider_env_file, timeout_s=300):
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
    checks["app_ready"] = command(
        engine, "exec", name, "curl", "-fsS", "--max-time", "10",
        "http://127.0.0.1:3773/"
    ).returncode == 0

    checks["provider_turn"] = check_provider_turn(
        engine, name, provider_env_file, timeout_s=timeout_s
    )
    checks["agent_cli"] = command(engine, "exec", name, "agent", "--help").returncode == 0
    checks["skills"] = command(engine, "exec", name, "agent", "skills", "doctor", "--json").returncode == 0
    checks["desktop_transport"] = command(
        engine, "exec", name, "agent", "tools", "doctor", "--json", "--only", "ghostship-bladebro"
    ).returncode == 0
    return checks


def check_provider_turn(engine, name, provider_env_file, timeout_s=300):
    """Prove a trusted free T3 route only when its static API key is projected."""
    try:
        env_names = {
            line.split("=", 1)[0]
            for line in Path(provider_env_file).read_text().splitlines()
            if "=" in line and line.split("=", 1)[1]
        }
    except OSError:
        env_names = set()
    providers = [provider for provider, env_name in API_KEY_ROUTE_ENV.items()
                 if env_name in env_names]
    if not providers:
        raise RuntimeError(
            "provider_turn refused: filtered projection has no static API key for an approved free route"
        )
    for provider in providers:
        pick = command(engine, "exec", name, "agent", "models", "pick",
                       "--role", "worker", "--provider", provider, "--json")
        if pick.returncode:
            continue
        try:
            payload = json.loads(pick.stdout)
            selection = payload.get("data", {}).get("pick") or {}
        except (ValueError, AttributeError):
            continue
        if (not isinstance(selection, dict)
                or not isinstance(selection.get("model"), str)
                or not selection.get("model")
                or selection.get("provider") != provider
                or selection.get("billing") not in ("free", "promotion")
                or selection.get("approved_free") is not True
                or selection.get("execution") != "t3"
                or selection.get("available") is not True):
            continue
        route = f"{provider}/{selection.get('model') or ''}"
        if route.endswith("/"):
            continue
        proof = command(
            engine, "exec", name, "agent", "models", "prove", route,
            "--wait", str(min(max(timeout_s - 30, 1), 240)), "--json",
            timeout=min(timeout_s, 270),
        )
        if proof.returncode == 0:
            return True
    raise RuntimeError(
        "provider_turn failed: picker found no available trusted free T3 route backed by a filtered static API key"
    )


def candidate_agent_path(engine, name, candidate_home_target):
    result = command(
        engine, "exec", name, "readlink", "-f",
        f"{candidate_home_target}/.local/state/ghostship-t3-tools/current",
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def accept(state_dir, image_archive, podman_bin, candidate_socket, home_dir,
           volumes=(), systemctl_bin="systemctl",
           command_fn=command, identity_fn=None, candidate_uid=None,
           candidate_runtime_dir=None, provider_secrets_file=None, tooling_path=None,
           expected_agent_revision=None, candidate_home_target="/candidate-home"):
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
    candidate_runtime_dir = Path(candidate_runtime_dir or tempfile.gettempdir())
    candidate_runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidate_tmp = Path(tempfile.mkdtemp(prefix="t3code-candidate-", dir=candidate_runtime_dir))
    os.chown(candidate_tmp, candidate_uid, candidate_uid)
    home_copy = candidate_tmp / "home"
    input_copy = candidate_tmp / "inputs"
    provider_env = candidate_tmp / "provider.env"
    created = False
    manager_started = False
    checks = {}
    try:
        stage_candidate_inputs(home_dir, home_copy, input_copy, candidate_uid, tooling_path)
        write_provider_env(provider_secrets_file, provider_env)
        server_overrides, bootstrap_overrides = write_candidate_systemd_overrides(candidate_tmp)
        manager_started = True
        subprocess.run([systemctl_bin, "start", "t3code-podman-candidate.service"],
                       check=True, timeout=30)
        assert_ok(engine, "load", "--input", str(image_archive), timeout=300)
        volumes = validate_candidate_mounts(volumes) + [
            f"{home_copy}:{candidate_home_target}:rw",
            f"{input_copy}:/run/t3code-candidate-inputs:ro",
            f"{server_overrides}:/etc/systemd/system/t3code-server.service.d:ro",
            f"{bootstrap_overrides}:/etc/systemd/system/t3code-bootstrap.service.d:ro",
        ]
        args = ["run", "--detach", "--name", name, "--hostname", name,
                "--userns=keep-id:uid=3000,gid=3000",
                "--systemd=always", "--cap-drop=ALL", "--security-opt=unmask=/proc/*",
                "--pids-limit=2048", "--network=slirp4netns",
                "--env=GHOSTSHIP_ROUTE_POLICY_PATH=/etc/ghostship/route-policy.json",
                "--env=GHOSTSHIP_MODEL_EVIDENCE_PATH=/tmp/t3code-candidate-model-evidence.jsonl",
                "--env-file", str(provider_env)]
        caps = json.loads(Path(__file__).with_name("runtime-caps.json").read_text())
        for cap in caps:
            args.extend(("--cap-add", cap))
        for item in volumes:
            args.extend(("--volume", str(item)))
        args.extend(("--volume", f"{candidate_socket}:/var/run/podman/podman.sock:rw"))
        created = True
        # This leaf unit does not pull in multi-user.target's timers and automations.
        args.extend((image_tag, "--unit=t3code-server.service"))
        assert_ok(engine, *args, timeout=300)
        checks = check_candidate(engine, name, provider_env)
        agent_path = candidate_agent_path(engine, name, candidate_home_target)
        if tooling_path and agent_path != str(Path(tooling_path).resolve()):
            checks["agent_cli"] = False
        after = identity_fn()
        if before != after:
            raise RuntimeError("production T3 identity changed during candidate acceptance")
        if any(checks.get(key) is not True for key in CHECKS):
            raise RuntimeError("candidate acceptance failed; receipt not written")
        receipt = {
            "deployment_id": desired,
            "image_id": image_id,
            "agent_revision": expected_agent_revision,
            "agent_path": agent_path,
            "provider_secret_inode": (str(Path(provider_secrets_file).stat().st_ino)
                                      if provider_secrets_file else None),
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
        cleanup_error = None
        if created:
            removed = command_fn(engine, "rm", "--force", "--time", "10", name, timeout=30)
            if removed.returncode:
                cleanup_error = "candidate container teardown failed"
        if manager_started:
            try:
                subprocess.run([systemctl_bin, "stop", "t3code-podman-candidate.service"],
                               check=True, timeout=30)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                cleanup_error = "candidate Podman manager teardown failed"
        try:
            remove_candidate_workspace(candidate_tmp)
        except OSError:
            cleanup_error = "candidate acceptance workspace teardown failed"
        if candidate_tmp.exists():
            cleanup_error = "candidate acceptance workspace teardown failed"
        after = identity_fn()
        if before != after or cleanup_error:
            receipt_path.unlink(missing_ok=True)
        if cleanup_error:
            raise RuntimeError(cleanup_error)
        if before != after:
            raise RuntimeError("production T3 identity changed during candidate teardown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--image-archive", required=True)
    parser.add_argument("--podman-bin", default="podman")
    parser.add_argument("--candidate-socket", default="/run/t3code-podman-candidate/podman.sock")
    parser.add_argument("--home-dir", required=True)
    parser.add_argument("--candidate-runtime-dir", required=True)
    parser.add_argument("--provider-secrets-file")
    parser.add_argument("--tooling-path")
    parser.add_argument("--agent-revision")
    parser.add_argument("--candidate-home-target", required=True)
    parser.add_argument("--volume", action="append", default=[])
    parser.add_argument("--systemctl-bin", default="systemctl")
    parser.add_argument("--candidate-uid", type=int, required=True)
    args = parser.parse_args()
    accept(args.state_dir, args.image_archive, args.podman_bin, args.candidate_socket,
           args.home_dir, args.volume, args.systemctl_bin,
           candidate_uid=args.candidate_uid,
           candidate_runtime_dir=args.candidate_runtime_dir,
           provider_secrets_file=args.provider_secrets_file,
           tooling_path=args.tooling_path,
           expected_agent_revision=args.agent_revision,
           candidate_home_target=args.candidate_home_target)


if __name__ == "__main__":
    main()
