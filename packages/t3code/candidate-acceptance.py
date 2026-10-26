"""Accept a new T3 image in disposable candidate storage before pickup."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
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
T3_FREE_PROVIDER = "opencode-free"
MODEL_ROUTING_TARGET = "/run/ghostship-integrations/model-routing.json"
ALLOWED_CANDIDATE_MOUNTS = {
    "/etc/ghostship/route-policy.json": "/etc/ghostship/route-policy.json",
    "/etc/ghostship/approved-free-workers.json": "/etc/ghostship/approved-free-workers.json",
    "/nix/store": "/nix/store",
}


def stage_candidate_inputs(source_home, candidate_home, candidate_inputs, candidate_uid,
                           tooling_path=None, candidate_home_target="/home/t3code",
                           stage_toolchain=False, approved_free_workers_file=None):
    """Stage a fresh HOME plus a read-only tree with only provider/agent inputs."""
    source_home = Path(source_home)
    candidate_home = Path(candidate_home)
    candidate_inputs = Path(candidate_inputs)
    staged_toolchain = None
    candidate_home.mkdir(mode=0o700)
    candidate_inputs.mkdir(mode=0o700)
    if tooling_path:
        stage_candidate_provider_settings(source_home, candidate_home, candidate_home_target)
        stage_candidate_opencode_catalog(source_home, candidate_home)
        if approved_free_workers_file:
            stage_candidate_provider_auth(
                source_home, candidate_home, approved_free_workers_file
            )
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
    probe = Path(__file__).with_name("provider-turn-probe.py")
    if probe.is_file():
        staged_probe = candidate_inputs / probe.name
        shutil.copyfile(probe, staged_probe)
        staged_probe.chmod(0o444)
    if stage_toolchain:
        staged_toolchain = stage_candidate_toolchain(
            source_home, candidate_home, candidate_uid, candidate_home_target
        )
    for path in (candidate_home, candidate_inputs, *candidate_home.rglob("*"),
                 *candidate_inputs.rglob("*")):
        if path.is_symlink():
            # Rootless keep-id maps the staging owner to container UID 3000.
            # A host-root-owned symlink is unmapped there and container setup
            # cannot chown it, even when the link's parent is writable.
            os.lchown(path, candidate_uid, candidate_uid)
        else:
            os.chown(path, candidate_uid, candidate_uid)
    return staged_toolchain


def stage_candidate_provider_settings(source_home, candidate_home,
                                      candidate_home_target="/home/t3code"):
    """Project only the non-secret opencode-free instance from production settings."""
    source = Path(source_home) / ".t3/userdata/settings.json"
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("production T3 provider settings are unavailable")
    try:
        document = json.loads(source.read_text())
    except (OSError, ValueError):
        raise RuntimeError("production T3 provider settings are unreadable") from None
    instances = document.get("providerInstances") if isinstance(document, dict) else None
    instance = instances.get(T3_FREE_PROVIDER) if isinstance(instances, dict) else None
    if (not isinstance(instance, dict) or instance.get("driver") != "opencode"
            or instance.get("enabled") is not True):
        raise RuntimeError("production opencode-free T3 provider is not enabled")
    source_config = instance.get("config")
    binary = source_config.get("binaryPath") if isinstance(source_config, dict) else None
    if not isinstance(binary, str) or not binary or "\n" in binary:
        raise RuntimeError("production opencode-free provider configuration is invalid")
    allowed_env = {
        "OPENCODE_DISABLE_FREE_MODELS", "OPENCODE_MODELS_PATH",
        "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    }
    environment = []
    for item in instance.get("environment", []):
        if not isinstance(item, dict) or item.get("name") not in allowed_env:
            continue
        name, value = item.get("name"), item.get("value")
        if not isinstance(value, str) or "\n" in value or "\0" in value:
            raise RuntimeError("production opencode-free provider environment is invalid")
        if name == "OPENCODE_DISABLE_FREE_MODELS":
            if value.lower() not in ("true", "false", "1", "0", "yes", "no", ""):
                raise RuntimeError("production opencode-free model setting is invalid")
        else:
            expected_home = PurePosixPath(candidate_home_target)
            target = PurePosixPath(value)
            try:
                target.relative_to(expected_home)
            except ValueError:
                raise RuntimeError("production opencode-free path leaves the T3 home") from None
        environment.append({"name": name, "value": value})
    names = {item["name"] for item in environment}
    if "OPENCODE_MODELS_PATH" not in names:
        raise RuntimeError("production opencode-free models path is missing")
    projected = {
        "providerInstances": {
            T3_FREE_PROVIDER: {
                "driver": "opencode",
                "enabled": True,
                "config": {"binaryPath": binary},
                "environment": environment,
            }
        }
    }
    settings = Path(candidate_home) / ".t3/userdata/settings.json"
    settings.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings.write_text(json.dumps(projected, sort_keys=True) + "\n")
    settings.chmod(0o600)


def stage_candidate_opencode_catalog(source_home, candidate_home):
    """Stage OpenCode's public source and filtered catalogs for candidate startup."""
    source = Path(source_home) / ".cache/opencode/models.json"
    filtered = Path(source_home) / ".local/state/t3code-opencode/models.json"
    for path in (source, filtered):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("production OpenCode model catalog is unavailable")
        try:
            catalog = json.loads(path.read_text())
        except (OSError, ValueError):
            raise RuntimeError("production OpenCode model catalog is unreadable") from None
        if (not isinstance(catalog, dict) or not catalog
                or any(not isinstance(value, dict) for value in catalog.values())):
            raise RuntimeError("production OpenCode model catalog is malformed")
        target = Path(candidate_home) / path.relative_to(Path(source_home))
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o444)


def stage_candidate_provider_auth(source_home, candidate_home, approved_file):
    """Copy only auth entries for owner-approved free providers into the candidate HOME."""
    auth_source = Path(source_home) / ".local/share/opencode/auth.json"
    if auth_source.is_symlink() or not auth_source.is_file():
        return False
    try:
        auth = json.loads(auth_source.read_text())
        approvals = json.loads(Path(approved_file).read_text())
    except (OSError, ValueError):
        raise RuntimeError("production provider auth projection is unreadable") from None
    entries = approvals.get("entries") if isinstance(approvals, dict) else None
    if not isinstance(auth, dict) or not isinstance(entries, list):
        raise RuntimeError("production provider auth projection is malformed")
    providers = {entry.get("provider") for entry in entries
                 if isinstance(entry, dict) and isinstance(entry.get("provider"), str)}
    projected = {provider: auth[provider] for provider in providers if provider in auth}
    if not projected:
        return False
    target = Path(candidate_home) / ".local/share/opencode/auth.json"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_text(json.dumps(projected, sort_keys=True) + "\n")
    target.chmod(0o600)
    return True


def stage_candidate_model_routing(source_file, candidate_tmp, candidate_uid):
    """Snapshot the live routing catalog into private candidate scratch."""
    source = Path(source_file)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
        raise RuntimeError("live model routing snapshot is unavailable")
    try:
        document = json.loads(source.read_text())
    except (OSError, ValueError):
        raise RuntimeError("live model routing snapshot is unreadable") from None
    if (not isinstance(document, dict)
            or document.get("schema") != "ghostship.ai-usage.routing"
            or document.get("schema_version") != 1
            or not isinstance(document.get("partial"), bool)):
        raise RuntimeError("live model routing snapshot is invalid")
    # A partial snapshot still carries the full catalog; one unread quota
    # source must not block every deploy. A failed source still does.
    coverage = document.get("coverage")
    failed = coverage.get("sources_failed") if isinstance(coverage, dict) else None
    if document["partial"] and (not isinstance(failed, int) or isinstance(failed, bool) or failed != 0):
        raise RuntimeError("live model routing snapshot has failed sources")
    target = Path(candidate_tmp) / "model-routing.json"
    shutil.copyfile(source, target)
    target.chmod(0o444)
    os.chown(target, candidate_uid, candidate_uid)
    return target


def resolve_container_home_path(source_home, path, container_home):
    """Resolve a container-home symlink against its host-side staged source."""
    source_home = Path(source_home).absolute()
    path = Path(path)
    if not path.is_absolute():
        path = source_home / path
    try:
        pending = list(path.relative_to(source_home).parts)
    except ValueError as error:
        raise ValueError("candidate runtime source is outside the T3 home") from error
    resolved = source_home

    def follow_symlinks(value):
        seen = set()
        while value.is_symlink():
            if value in seen:
                raise ValueError("candidate runtime source contains a symlink loop")
            seen.add(value)
            target = Path(os.readlink(value))
            if target.is_absolute():
                container_root = PurePosixPath(container_home)
                target_posix = PurePosixPath(str(target))
                try:
                    relative = target_posix.relative_to(container_root)
                except ValueError as error:
                    raise ValueError("candidate runtime symlink leaves the T3 home") from error
                value = source_home.joinpath(*relative.parts)
            else:
                value = value.parent / target
            value = Path(os.path.normpath(value))
            try:
                value.relative_to(source_home)
            except ValueError as error:
                raise ValueError("candidate runtime symlink leaves the T3 home") from error
        return value

    for part in pending:
        resolved = follow_symlinks(resolved) / part
        resolved = follow_symlinks(resolved)
    return resolved


def stage_candidate_toolchain(source_home, candidate_home, candidate_uid,
                              container_home="/home/t3code"):
    """Copy only the active CLI runtimes needed to boot a fresh candidate HOME.

    Container setup runs its network updater when these runtime markers are
    absent. Seeding the currently installed tools avoids promoting a candidate
    binary during acceptance (notably a known-bad T3 CLI release).
    """
    source_home = Path(source_home).absolute()
    candidate_home = Path(candidate_home)

    def required_dir(path, role):
        resolved = resolve_container_home_path(source_home, path, container_home)
        if not resolved.is_dir():
            raise RuntimeError(f"candidate requires the installed {role} runtime")
        return resolved

    def copy_tree(source, destination, role):
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f"candidate {role} destination already exists")
        shutil.copytree(source, destination, symlinks=True, copy_function=shutil.copy2)

    t3_root = source_home / ".local/share/t3code-tools/t3"
    t3_release = required_dir(t3_root / "current", "T3 CLI")
    if t3_release.parent != t3_root / "releases":
        raise RuntimeError("candidate T3 CLI release is outside its managed release tree")
    version = t3_release.name
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
        raise RuntimeError("candidate T3 CLI release has an invalid version")
    t3_binary = resolve_container_home_path(
        source_home, t3_release / "bin/t3", container_home
    )
    if not t3_binary.is_file() or not os.access(t3_binary, os.X_OK):
        raise RuntimeError("candidate requires an executable installed T3 CLI")
    runtime_version = t3_binary.parent
    runtime_root = source_home / ".t3/runtime/versions"
    if runtime_version.parent != runtime_root or not runtime_version.is_dir():
        raise RuntimeError("candidate T3 runtime is outside its managed version tree")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", runtime_version.name):
        raise RuntimeError("candidate T3 runtime has an invalid version")
    copy_tree(
        runtime_version,
        candidate_home / ".t3/runtime/versions" / runtime_version.name,
        "T3 runtime",
    )
    t3_destination = candidate_home / ".local/share/t3code-tools/t3"
    copy_tree(t3_release, t3_destination / "releases" / version, "T3 CLI")
    t3_link = t3_destination / "current"
    t3_link.symlink_to(f"releases/{version}")

    npm_root = source_home / ".local/share/t3code-tools/npm"
    codex_link = npm_root / "bin/codex"
    codex_binary = resolve_container_home_path(source_home, codex_link, container_home)
    codex_package = codex_binary.parents[1]
    if (codex_package.name != "codex" or codex_package.parent.name != "@openai"
            or not codex_binary.is_file() or not os.access(codex_binary, os.X_OK)):
        raise RuntimeError("candidate requires the installed Codex CLI runtime")
    copy_tree(
        codex_package,
        candidate_home / codex_package.relative_to(source_home),
        "Codex CLI",
    )
    codex_version = json.loads((codex_package / "package.json").read_text()).get("version")
    if not isinstance(codex_version, str) or not codex_version:
        raise RuntimeError("candidate Codex CLI package has no version")
    candidate_npm_bin = candidate_home / ".local/share/t3code-tools/npm/bin"
    candidate_npm_bin.mkdir(mode=0o700, parents=True, exist_ok=True)
    (candidate_npm_bin / "codex").symlink_to(os.readlink(codex_link))

    shared_agent_bin = source_home / ".local/state/t3code-shared-agents/bin"
    candidate_shared_agent_bin = candidate_home / ".local/state/t3code-shared-agents/bin"
    candidate_shared_agent_bin.mkdir(mode=0o700, parents=True, exist_ok=True)
    candidate_local_bin = candidate_home / ".local/bin"
    candidate_local_bin.mkdir(mode=0o700, parents=True, exist_ok=True)
    for tool in ("agent", "ghostship", "ghostship-bladebro"):
        source = shared_agent_bin / tool
        if source.is_symlink() or not source.is_file() or not os.access(source, os.X_OK):
            raise RuntimeError(f"candidate requires the installed {tool} launcher")
        shutil.copy2(source, candidate_shared_agent_bin / tool)
        (candidate_local_bin / tool).symlink_to(
            f"../state/t3code-shared-agents/bin/{tool}"
        )

    opencode_root = source_home / ".local/share/t3code-tools/opencode"
    opencode_release = required_dir(opencode_root / "current", "OpenCode CLI")
    if opencode_release.parent != opencode_root / "releases":
        raise RuntimeError("candidate OpenCode release is outside its managed release tree")
    opencode_version = opencode_release.name
    opencode_binary = opencode_release / "bin/opencode"
    if not opencode_binary.is_file() or not os.access(opencode_binary, os.X_OK):
        raise RuntimeError("candidate requires an executable installed OpenCode CLI")
    candidate_opencode_root = candidate_home / ".local/share/t3code-tools/opencode"
    copy_tree(
        opencode_release,
        candidate_opencode_root / "releases" / opencode_version,
        "OpenCode CLI",
    )
    (candidate_opencode_root / "current").symlink_to(
        f"releases/{opencode_version}"
    )
    opencode_link = npm_root / "bin/opencode"
    if not opencode_link.is_symlink():
        raise RuntimeError("candidate requires the managed OpenCode CLI shim")
    (candidate_npm_bin / "opencode").symlink_to(os.readlink(opencode_link))
    return {
        "t3": version,
        "codex": codex_version,
        "opencode": opencode_version,
    }


def stage_candidate_agent_store(podman_bin, source_home, candidate_tmp,
                                candidate_home, candidate_uid,
                                container_home="/home/t3code"):
    """Stage shared-agent wrappers and missing Nix closures from production read-only."""
    source_home = Path(source_home)
    wrappers = source_home / ".local/state/t3code-shared-agents/bin"
    targets = []
    for tool in ("agent", "ghostship", "ghostship-bladebro"):
        wrapper = wrappers / tool
        if not wrapper.is_file() or wrapper.is_symlink():
            raise RuntimeError(f"candidate requires the installed {tool} launcher")
        current = wrapper
        seen = set()
        for _ in range(4):
            if current in seen:
                raise RuntimeError("candidate shared-agent launcher contains a loop")
            seen.add(current)
            content = current.read_text()
            commands = [line for line in content.splitlines()
                        if line.startswith("exec ")]
            if len(commands) != 1:
                store_references = set(re.findall(
                    r"(?<![A-Za-z0-9_])(/nix/store/[0-9a-z]{32}-[A-Za-z0-9._+-]+)",
                    content,
                ))
                if not store_references:
                    raise RuntimeError("candidate shared-agent launcher has an unsupported format")
                targets.extend(sorted(store_references))
                break
            try:
                argv = shlex.split(commands[0][len("exec "):])
            except ValueError as error:
                argv = []
            if len(argv) != 2 or argv[1] != "$@":
                store_references = set(re.findall(
                    r"(?<![A-Za-z0-9_])(/nix/store/[0-9a-z]{32}-[A-Za-z0-9._+-]+)",
                    content,
                ))
                if not store_references:
                    raise RuntimeError("candidate shared-agent launcher has an unsupported format")
                targets.extend(sorted(store_references))
                break
            target = PurePosixPath(argv[0])
            container_root = PurePosixPath(container_home)
            try:
                relative = target.relative_to(container_root)
            except ValueError:
                relative = None
            if relative is not None:
                expected_root = (".local", "state", "ghostship")
                if (len(relative.parts) < 4 or relative.parts[:3] != expected_root
                        or any(part in (".", "..") for part in relative.parts)
                        or any(not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", part)
                               for part in relative.parts)):
                    raise RuntimeError("candidate shared-agent launcher points outside its managed tree")
                copied_wrapper = Path(candidate_home).joinpath(*relative.parts)
                if not copied_wrapper.exists():
                    copied_wrapper.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    copied = subprocess.run(
                        [podman_bin, "cp", f"t3code:{target}", str(copied_wrapper.parent)],
                        check=False, text=True, capture_output=True, timeout=120,
                    )
                    if copied.returncode or not copied_wrapper.is_file():
                        raise RuntimeError("candidate could not stage a shared-agent launcher")
                    parent = copied_wrapper.parent
                    while parent != Path(candidate_home):
                        os.chown(parent, candidate_uid, candidate_uid)
                        parent = parent.parent
                    os.chown(copied_wrapper, candidate_uid, candidate_uid)
                current = copied_wrapper
                continue
            if (not target.is_absolute() or target.parts[:3] != ("/", "nix", "store")
                    or len(target.parts) < 5
                    or not re.fullmatch(r"[0-9a-z]{32}-.+", target.parts[3])):
                raise RuntimeError("candidate shared-agent launcher points outside the Nix store")
            targets.append(str(PurePosixPath(*target.parts[:4])))
            break
        else:
            raise RuntimeError("candidate shared-agent launcher chain is too deep")

    query = subprocess.run(
        [podman_bin, "exec", "t3code", "nix", "path-info", "--recursive", "--json",
         *sorted(set(targets))], check=False, text=True, capture_output=True, timeout=120,
    )
    if query.returncode:
        raise RuntimeError("candidate could not inspect the installed shared-agent closure")
    try:
        closure = json.loads(query.stdout)
    except (TypeError, ValueError) as error:
        raise RuntimeError("candidate received an invalid shared-agent closure description") from error
    if not isinstance(closure, dict) or not closure:
        raise RuntimeError("candidate received an empty shared-agent closure description")

    candidate_store = Path(candidate_tmp) / "nix-store-overlay"
    candidate_store.mkdir(mode=0o755)
    staged = []
    for raw_path in sorted(closure):
        store_path = PurePosixPath(raw_path)
        if (not store_path.is_absolute() or store_path.parts[:3] != ("/", "nix", "store")
                or not re.fullmatch(r"[0-9a-z]{32}-.+", store_path.name)):
            raise RuntimeError("candidate shared-agent closure contains a non-store path")
        host_path = Path(raw_path)
        if host_path.exists():
            continue
        destination = candidate_store / store_path.name
        copied = subprocess.run(
            [podman_bin, "cp", f"t3code:{raw_path}", str(candidate_store)],
            check=False, text=True, capture_output=True, timeout=120,
        )
        if copied.returncode or not destination.exists():
            raise RuntimeError("candidate could not stage a missing shared-agent dependency")
        staged.append((str(destination), str(store_path)))
    return staged


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
        isolated_store_overlay = source == "/nix/store" and target == "/nix/store" and mode == "O"
        if (ALLOWED_CANDIDATE_MOUNTS.get(source) != target
                or (mode != "ro" and not isolated_store_overlay)):
            raise ValueError("candidate mount is outside the read-only acceptance allowlist")
    return list(volumes)


def candidate_name(deployment_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", deployment_id):
        raise ValueError("invalid T3 candidate deployment identifier")
    name = f"t3code-candidate-{deployment_id}"
    if len(name.encode("ascii")) > 64:
        suffix = hashlib.sha256(deployment_id.encode("ascii")).hexdigest()[:40]
        name = f"t3code-candidate-{suffix}"
    return name


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
        detail = next((line.strip() for line in reversed(result.stderr.splitlines())
                       if line.strip()), "")
        detail = re.sub(r"(?i)(token|secret|api[_-]?key)(\s*[=:]\s*)\S+",
                        r"\1\2[redacted]", detail)
        detail = re.sub(r"[0-9a-f]{32,}", "[redacted]", detail)
        detail = re.sub(r"/\S+", "[path]", detail)
        suffix = f" ({detail[:180]})" if detail else ""
        raise RuntimeError(f"candidate command failed: {args[0]}{suffix}")
    return result.stdout.strip()


def candidate_agent_command(engine, name, *args, timeout=180):
    """Run user-facing agent work with the configured T3 runtime identity."""
    return command(engine, "exec", "--user=3000:3000", name, *args,
                   timeout=timeout)


def candidate_error_category(result):
    output = result.stderr or result.stdout or ""
    detail = output.lower()
    if "ownership directory must be private" in detail:
        return "runtime-ownership"
    if "permission denied" in detail or "operation not permitted" in detail:
        return "permission"
    if "unrecognized arguments" in detail or "invalid choice" in detail:
        return "cli-arguments"
    if "no available" in detail or "no eligible" in detail or "no route" in detail:
        return "route-unavailable"
    if "not found" in detail or "no such file" in detail:
        return "command-not-found"
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if error is None and isinstance(payload.get("data"), dict):
            error = payload["data"].get("error")
        if isinstance(error, dict):
            code = error.get("code") or error.get("type")
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code):
                return "api-error-" + code.lower()
            return "api-error"
        if payload.get("ok") is False or payload.get("status") == "error":
            return "api-error"
    for line in reversed(output.splitlines()):
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):", line.strip())
        if match:
            return "exception-" + match.group(1).lower()
    return "command-error"


def candidate_error_summary(result):
    output = result.stderr or result.stdout or ""
    try:
        payload = json.loads(output)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if error is None and isinstance(payload.get("data"), dict):
            error = payload["data"].get("error")
        if isinstance(error, dict):
            value = error.get("code") or error.get("type") or "api-error"
            return re.sub(r"[^A-Za-z0-9_.-]", "-", str(value))[:64]
        if isinstance(error, str):
            # Return only known diagnostic words from arbitrary provider text.
            # Never echo the message: it may contain request data or secrets.
            safe_terms = {
                "auth", "unauthorized", "forbidden", "timeout", "network",
                "connection", "refused", "unavailable", "not_found", "rate_limit",
                "quota", "policy", "blocked", "unsupported", "invalid", "missing",
                "failed", "provider", "key", "model", "route", "api", "request",
                "response", "status", "error", "job", "interrupted",
            }
            terms = sorted(set(re.findall(r"[a-z_]+", error.lower())) & safe_terms)
            return "api-error-" + "-".join(terms[:8]) if terms else "api-error-text"
        data = payload.get("data")
        data_keys = sorted(data) if isinstance(data, dict) else []
        keys = sorted(payload)
        error_shape = type(error).__name__ if error is not None else "absent"
        return ("json-keys-" + "-".join(keys[:8]) + "-data-" + "-".join(data_keys[:8])
                + "-error-type-" + error_shape)
    line = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "")
    line = re.sub(r"(?i)([A-Z0-9_]*(?:TOKEN|SECRET|API[_-]?KEY)[A-Z0-9_]*)(\s*[=:]\s*)\S+",
                  r"\1\2[redacted]", line)
    line = re.sub(r"[0-9a-f]{32,}", "[redacted]", line)
    line = re.sub(r"/[A-Za-z0-9._/+:-]+", "[path]", line)
    line = re.sub(r"(?i)t3code-candidate-[A-Za-z0-9-]+", "[candidate]", line)
    return re.sub(r"[^A-Za-z0-9_.-]", "-", line)[:96] or "empty-output"


def check_candidate(engine, name, provider_env_file, timeout_s=300, tooling_path=None):
    # The isolated manager starts one leaf unit to avoid target-wide timers.
    # Production exposes the app through this separate proxy unit on :3773.
    # Start that same serving path explicitly in the disposable candidate.
    proxy_deadline = time.monotonic() + min(timeout_s, 30)
    while True:
        proxy_start = command(
            engine, "exec", name, "systemctl", "start", "t3code-access-proxy.service",
            timeout=15,
        )
        if proxy_start.returncode == 0:
            break
        state = command(engine, "inspect", name, "--format", "{{json .State}}")
        try:
            state_data = json.loads(state.stdout)
        except (TypeError, ValueError):
            state_data = {}
        if state_data.get("Running") is not True:
            exit_code = state_data.get("ExitCode")
            detail = f" (exit code {exit_code})" if isinstance(exit_code, int) else ""
            raise RuntimeError(f"candidate container exited before proxy startup{detail}")
        if time.monotonic() >= proxy_deadline:
            raise RuntimeError("candidate access proxy failed to start")
        time.sleep(2)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if command(engine, "exec", name, "curl", "-fsS", "--max-time", "5",
                   "http://127.0.0.1:3773/").returncode == 0:
            break
        state = command(engine, "inspect", name, "--format", "{{json .State}}")
        if state.returncode:
            raise RuntimeError("candidate container exited before app readiness")
        try:
            state_data = json.loads(state.stdout)
        except (TypeError, ValueError):
            state_data = {}
        if state_data.get("Running") is not True:
            exit_code = state_data.get("ExitCode")
            detail = f" (exit code {exit_code})" if isinstance(exit_code, int) else ""
            raise RuntimeError(f"candidate container exited before app readiness{detail}")
        time.sleep(2)
    else:
        raise RuntimeError("candidate app did not become ready")

    checks = {}
    checks["app_ready"] = command(
        engine, "exec", name, "curl", "-fsS", "--max-time", "10",
        "http://127.0.0.1:3773/"
    ).returncode == 0

    register_candidate_workspace(engine, name)
    provider_route = check_provider_turn(
        engine, name, provider_env_file, timeout_s=timeout_s,
        tooling_path=tooling_path,
    )
    checks["provider_turn"] = bool(provider_route)
    checks["provider_turn_route"] = provider_route
    checks["agent_cli"] = candidate_agent_command(
        engine, name, "agent", "--help"
    ).returncode == 0
    checks["skills"] = candidate_agent_command(
        engine, name, "agent", "skills", "doctor", "--json"
    ).returncode == 0
    checks["desktop_transport"] = candidate_agent_command(
        engine, name, "agent", "tools", "doctor", "--json", "--only", "ghostship-bladebro"
    ).returncode == 0
    return checks


def register_candidate_workspace(engine, name):
    """Register the disposable /workspace so the real T3 probe can launch."""
    result = candidate_agent_command(
        engine, name, "t3", "project", "add", "/workspace",
        "--title", "Candidate acceptance",
    )
    if result.returncode:
        category = candidate_error_category(result)
        summary = candidate_error_summary(result)
        raise RuntimeError(
            f"candidate workspace registration failed ({category}-{summary})"
        )


def check_provider_turn(engine, name, provider_env_file, timeout_s=300, tooling_path=None):
    """Prove the live picker route with a real native provider turn."""
    del provider_env_file  # This route is served by the T3 opencode-free instance.
    diagnostics = candidate_provider_diagnostics(engine, name)
    route_result = candidate_agent_command(engine, name, "agent", "models", "--json")
    routes = candidate_t3_routes(route_result)
    route_summary = candidate_t3_route_summary(route_result)
    pick = candidate_agent_command(
        engine, name, "agent", "models", "pick", "--role", "worker",
        "--kind", "code", "--json",
    )
    initial_route = None
    if pick.returncode:
        category = candidate_error_category(pick)
        summary = candidate_error_summary(pick)
        if "model-unavailable" not in summary.lower():
            raise RuntimeError(
                f"provider_turn failed: live T3 picker exited {pick.returncode} "
                f"({category}-{summary}); candidate_state={diagnostics}"
            )
    else:
        try:
            payload = json.loads(pick.stdout)
            selection = payload.get("data", {}).get("pick") or {}
        except (ValueError, AttributeError):
            selection = {}
        if not valid_t3_acceptance_route(selection):
            raise RuntimeError(
                "provider_turn failed: live picker returned no approved available free or subscription T3 route"
            )
        initial_route = f"{selection['provider']}/{selection['model']}"
    routes = ([initial_route] if initial_route else []) + [
        route for route in routes if route != initial_route
    ]
    if not routes:
        raise RuntimeError(
            "provider_turn failed: model-unavailable and live catalog has no approved available T3 fallback "
            f"(candidate_state={diagnostics}; catalog={route_summary})"
        )
    if not tooling_path:
        raise RuntimeError("provider_turn failed: candidate agent tools path unavailable")
    failures = []
    # A route-level failure (provider API error, quota, unavailable model) says
    # nothing about the image: try the next admitted route. An image defect fails
    # every route. Bounded so a broken image still fails fast (config#616).
    for route in routes[:MAX_ACCEPTANCE_ROUTES]:
        proof = candidate_agent_command(
            engine, name, "agent", "run", "--", "python3",
            "/run/t3code-candidate-inputs/provider-turn-probe.py",
            route, "--wait", str(min(max(timeout_s - 30, 1), 240)),
            timeout=min(timeout_s, 270),
        )
        if proof.returncode == 0:
            return route
        category = candidate_error_category(proof)
        summary = candidate_error_summary(proof)
        failures.append(f"{route}:{category}-{summary}")
    raise RuntimeError(
        "provider_turn failed: no live picker route proved a turn ("
        + ",".join(failures[:8])
        + f"); candidate_state={diagnostics}; catalog={route_summary}"
    )


def valid_t3_free_route(selection):
    return (
        isinstance(selection, dict)
        and isinstance(selection.get("provider"), str)
        and isinstance(selection.get("model"), str)
        and bool(selection["model"])
        and selection.get("billing") in ("free", "promotion")
        and selection.get("approved_free") is True
        and selection.get("execution") == "t3"
        and selection.get("available") is True
    )


MAX_ACCEPTANCE_ROUTES = 3

# Protected premium allowances never pay for an image acceptance probe.
PROTECTED_ACCEPTANCE_PROVIDERS = frozenset({"codex", "claude", "claudeAgent"})


def valid_t3_acceptance_route(selection):
    """An approved free T3 route, or else an admitted subscription T3 route.

    The image gate must not depend on a free route happening to have quota
    (config#616): one short probe turn on an admitted subscription route such as
    DeepSeek Flash costs almost nothing. Codex and Claude stay excluded, and the
    receipt records the route that proved the turn.
    """
    if valid_t3_free_route(selection):
        return True
    return (
        isinstance(selection, dict)
        and isinstance(selection.get("provider"), str)
        and isinstance(selection.get("model"), str)
        and bool(selection["model"])
        and selection.get("billing") == "subscription"
        and selection["provider"] not in PROTECTED_ACCEPTANCE_PROVIDERS
        and selection.get("execution") == "t3"
        and selection.get("available") is True
    )


def candidate_t3_routes(result):
    try:
        payload = json.loads(result.stdout)
        rows = payload.get("data", {}).get("selected", [])
    except (TypeError, ValueError, AttributeError):
        return []
    routes = []
    for row in rows:
        if valid_t3_acceptance_route(row):
            route = f"{row['provider']}/{row['model']}"
            if route not in routes:
                routes.append(route)
    return routes


def candidate_t3_route_summary(result):
    try:
        payload = json.loads(result.stdout)
        rows = payload.get("data", {}).get("selected", [])
    except (TypeError, ValueError, AttributeError):
        return "unavailable"
    if not isinstance(rows, list):
        return "unavailable"
    summary = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        provider = row.get("provider")
        model = row.get("model")
        if not isinstance(provider, str) or not isinstance(model, str):
            continue
        safe_provider = re.sub(r"[^A-Za-z0-9_.-]", "-", provider)[:64]
        safe_model = re.sub(r"[^A-Za-z0-9_./:-]", "-", model)[:96]
        summary.append(
            f"{safe_provider}/{safe_model}:{row.get('execution')}:{row.get('available')}:{row.get('approved_free')}"
        )
    return ",".join(summary[:8]) or "empty"


def candidate_provider_diagnostics(engine, name):
    """Summarize provider input presence without reading secret values."""
    script = (
        "for pair in settings:/home/t3code/.t3/userdata/settings.json "
        "source_models:/home/t3code/.cache/opencode/models.json "
        "filtered_models:/home/t3code/.local/state/t3code-opencode/models.json "
        "free_database:/home/t3code/.config/opencode-free/data/opencode/opencode.db "
        "provider_secrets:/run/secrets/t3code.env "
        "routing_snapshot:/run/ghostship-integrations/model-routing.json "
        "openrouter_auth:/home/t3code/.local/share/opencode/auth.json "
        "codex_auth:/home/t3code/.codex/auth.json "
        "route_policy:/etc/ghostship/route-policy.json "
        "approved_free:/etc/ghostship/approved-free-workers.json; do "
        "key=${pair%%:*}; path=${pair#*:}; "
        "if [ -e \"$path\" ]; then printf '%s=present,' \"$key\"; "
        "else printf '%s=missing,' \"$key\"; fi; done; "
        "pid=$(systemctl show t3code-server.service -p MainPID --value 2>/dev/null || true); "
        "for key in OPENCODE_MODELS_PATH OPENROUTER_API_KEY GOOGLE_GENERATIVE_AI_API_KEY NVIDIA_API_KEY; do "
        "if [ -n \"$pid\" ] && [ \"$pid\" != 0 ] && "
        "tr '\\0' '\\n' <\"/proc/$pid/environ\" 2>/dev/null | cut -d= -f1 | grep -Fxq \"$key\"; "
        "then printf '%s=present,' \"$key\"; else printf '%s=missing,' \"$key\"; fi; done"
        " ; if [ \"${GHOSTSHIP_MODEL_RANKINGS_PATH:-}\" = /run/ghostship-integrations/model-routing.json ] "
        "&& [ -s /run/ghostship-integrations/model-routing.json ]; then printf 'routing_env=present,'; "
        "else printf 'routing_env=missing,'; fi"
    )
    result = command(engine, "exec", name, "sh", "-c", script, timeout=20)
    if result.returncode:
        return "unavailable"
    return re.sub(r"[^A-Za-z0-9_=,-]", "-", result.stdout.strip())[:400] or "empty"


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
           expected_agent_revision=None, candidate_home_target="/candidate-home",
           deployment_id=None, model_routing_file=None):
    """Boot, check, record and remove one candidate without changing production."""
    identity_fn = identity_fn or _probe.identity
    candidate_uid = os.getuid() if candidate_uid is None else int(candidate_uid)
    validated_volumes = validate_candidate_mounts(volumes)
    approved_workers_file = next(
        (str(volume).split(":", 2)[0] for volume in validated_volumes
         if str(volume).split(":", 2)[1:2] == ["/etc/ghostship/approved-free-workers.json"]),
        None,
    )
    state_dir = Path(state_dir)
    desired = deployment_id or (state_dir / "desired").read_text().strip()
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
        staged_toolchain = stage_candidate_inputs(
            home_dir, home_copy, input_copy, candidate_uid, tooling_path,
            candidate_home_target, stage_toolchain=bool(tooling_path),
            approved_free_workers_file=approved_workers_file,
        )
        write_provider_env(provider_secrets_file, provider_env)
        os.chown(provider_env, candidate_uid, candidate_uid)
        routing_copy = (
            stage_candidate_model_routing(model_routing_file, candidate_tmp, candidate_uid)
            if model_routing_file else None
        )
        candidate_workspace = candidate_tmp / "workspace"
        candidate_workspace.mkdir(mode=0o700)
        (candidate_workspace / "README.txt").write_text(
            "Disposable workspace for candidate acceptance.\n"
        )
        os.chown(candidate_workspace, candidate_uid, candidate_uid)
        os.chown(candidate_workspace / "README.txt", candidate_uid, candidate_uid)
        server_overrides, bootstrap_overrides = write_candidate_systemd_overrides(candidate_tmp)
        agent_store_paths = (
            stage_candidate_agent_store(
                podman_bin, home_dir, candidate_tmp, home_copy, candidate_uid,
                candidate_home_target,
            )
            if tooling_path else []
        )
        manager_started = True
        subprocess.run([systemctl_bin, "start", "t3code-podman-candidate.service"],
                       check=True, timeout=30)
        assert_ok(engine, "load", "--input", str(image_archive), timeout=300)
        volumes = validated_volumes + [
            f"{home_copy}:{candidate_home_target}:rw",
            f"{candidate_workspace}:/workspace:rw",
            f"{input_copy}:/run/t3code-candidate-inputs:ro",
            f"{provider_env}:/run/secrets/t3code.env:ro",
            *([f"{routing_copy}:{MODEL_ROUTING_TARGET}:ro"] if routing_copy else []),
            f"{server_overrides}:/etc/systemd/system/t3code-server.service.d:ro",
            f"{bootstrap_overrides}:/etc/systemd/system/t3code-bootstrap.service.d:ro",
        ]
        args = ["run", "--detach", "--name", name, "--hostname", name,
                # Rootless keep-id maps the host candidate account to container
                # UID 3000. Without this override Podman also starts PID 1 as
                # UID 3000, so systemd cannot manage the system unit tree.
                "--user=0:0",
                "--userns=keep-id:uid=3000,gid=3000",
                "--systemd=always", "--cap-drop=ALL", "--security-opt=unmask=/proc/*",
                "--pids-limit=2048", "--network=slirp4netns",
                "--env=GHOSTSHIP_ROUTE_POLICY_PATH=/etc/ghostship/route-policy.json",
                "--env=GHOSTSHIP_MODEL_EVIDENCE_PATH=/tmp/t3code-candidate-model-evidence.jsonl",
                *( [f"--env=GHOSTSHIP_MODEL_RANKINGS_PATH={MODEL_ROUTING_TARGET}"] if routing_copy else [] ),
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
        for source, _target in agent_store_paths:
            assert_ok(engine, "cp", source, f"{name}:/nix/store/", timeout=120)
        checks = check_candidate(engine, name, provider_env, tooling_path=tooling_path)
        agent_path = candidate_agent_path(engine, name, candidate_home_target)
        if tooling_path and agent_path != str(Path(tooling_path).resolve()):
            checks["agent_cli"] = False
        after = identity_fn()
        if before != after:
            raise RuntimeError("production T3 identity changed during candidate acceptance")
        if any(checks.get(key) is not True for key in CHECKS):
            failed = ",".join(key for key in CHECKS if checks.get(key) is not True)
            raise RuntimeError(
                f"candidate acceptance failed; failed_checks={failed or 'unknown'}"
            )
        receipt = {
            "deployment_id": desired,
            "image_id": image_id,
            "agent_revision": expected_agent_revision,
            "agent_path": agent_path,
            "provider_secret_inode": (str(Path(provider_secrets_file).stat().st_ino)
                                      if provider_secrets_file else None),
            "candidate_name": name,
            "candidate_toolchain": staged_toolchain,
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
    parser.add_argument("--model-routing-file", default="/var/lib/ghostship-ai-usage/routing.json")
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
           candidate_home_target=args.candidate_home_target,
           model_routing_file=args.model_routing_file)


if __name__ == "__main__":
    main()
