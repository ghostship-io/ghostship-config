"""Accept a new T3 image in disposable candidate storage before pickup."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

_probe_spec = importlib.util.spec_from_file_location(
    "t3code_hardening_probe", Path(__file__).with_name("hardening-probe.py")
)
_probe = importlib.util.module_from_spec(_probe_spec)
_probe_spec.loader.exec_module(_probe)

CHECKS = ("app_ready", "provider_turn", "agent_cli", "skills", "desktop_cli")
HOME_DIRS = (".agents/skills",)
T3_FREE_PROVIDER = "opencode-free"
# Acceptance names one exact owner-approved worker primary. Dispatch's picker,
# quota windows and snapshot mapping may report availability; they must not
# decide whether the candidate image can run a turn.
ACCEPTANCE_PRIMARY_ROUTE = ("opencode", "opencode-go/deepseek-v4.1-flash")
# The route-policy's one admitted free worker route. The previous model
# (opencode/glm-5.3-flash-free) began returning api-error-execution-execution
# at acceptance time; this is the admitted free route the policy already names.
ACCEPTANCE_ROUTE = ("opencode-free", "opencode/deepseek-v4.1-flash-free")
ACCEPTANCE_ROUTE_FILE = "/etc/ghostship/t3code-acceptance-route.json"
REHEARSAL_SCHEMA = "ghostship.t3code-rehearsal/v1"
SECRET_FILE_NAMES = frozenset({"auth.json", "t3code.env", "credentials.json"})
ACCEPTANCE_EFFORT = "high"
MODEL_ROUTING_TARGET = "/run/ghostship-integrations/model-routing.json"
ALLOWED_CANDIDATE_MOUNTS = {
    "/etc/ghostship/route-policy.json": "/etc/ghostship/route-policy.json",
    "/etc/ghostship/approved-free-workers.json": "/etc/ghostship/approved-free-workers.json",
    "/nix/store": "/nix/store",
}


def valid_runtime_layout(source_home, t3_release, runtime_version):
    """Accept both managed layouts for the T3 runtime directory.

    The release directory is the runtime when update-t3.py installs the whole app
    under t3/releases/<version>; older installations link the binary into a
    separate .t3/runtime/versions tree. Comparing resolved paths matters because
    the home itself may be a symlink.
    """
    if not runtime_version.is_dir():
        return False
    if runtime_version == t3_release:
        return True
    runtime_root = (source_home / ".t3/runtime/versions").resolve()
    return runtime_version.parent == runtime_root


def assert_candidate_auth_free(candidate_home, candidate_inputs, provider_env,
                               allow_missing_settings=False):
    """Refuse to start a candidate carrying any provider credential artifact.

    A missing provider settings file is a failure unless the caller explicitly
    says this is a rehearsal with no staged tooling; absence is never inferred.
    """
    for root in (Path(candidate_home), Path(candidate_inputs)):
        for path in root.rglob("*"):
            if path.is_file() and path.name == "auth.json":
                raise PreconditionError("candidate carries an auth.json")
            if path.is_file() and path.name == "opencode.jsonc":
                try:
                    config = json.loads(path.read_text())
                except (OSError, ValueError):
                    raise PreconditionError("candidate OpenCode config is unreadable") from None
                providers = config.get("provider") if isinstance(config, dict) else None
                if not isinstance(providers, dict) or set(providers) != {"opencode"}:
                    raise PreconditionError("candidate OpenCode config names another provider")
    settings = Path(candidate_home) / ".t3/userdata/settings.json"
    if not settings.exists():
        if not allow_missing_settings:
            raise PreconditionError("candidate provider settings are unreadable")
    else:
        try:
            document = json.loads(settings.read_text())
        except (OSError, ValueError):
            raise PreconditionError("candidate provider settings are unreadable") from None
        instances = document.get("providerInstances") if isinstance(document, dict) else None
        if not isinstance(instances, dict) or set(instances) != {T3_FREE_PROVIDER}:
            raise PreconditionError("candidate provider instances are not the anonymous Zen instance")
        environment = instances[T3_FREE_PROVIDER].get("environment")
        if not isinstance(environment, list):
            raise PreconditionError("candidate provider environment is invalid")
        for item in environment:
            if not isinstance(item, dict) or item.get("name") not in ANONYMOUS_SETTINGS_ENV_ALLOWLIST:
                raise PreconditionError("candidate provider environment is not allowlisted")
    try:
        keys = {line.split("=", 1)[0].strip() for line in Path(provider_env).read_text().splitlines()
                if "=" in line and line.strip() and not line.strip().startswith("#")}
    except OSError:
        keys = set()
    if keys - ANONYMOUS_ENV_ALLOWLIST:
        raise PreconditionError("candidate provider env file carries a non-allowlisted value")


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
        stage_candidate_opencode_free(source_home, candidate_home, candidate_home_target)
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
    observer = Path(__file__).with_name("rehearsal-isolation.py")
    if observer.is_file():
        staged_observer = candidate_inputs / observer.name
        shutil.copyfile(observer, staged_observer)
        staged_observer.chmod(0o444)
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
    """Project only the non-secret opencode-free instance."""
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
            },
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


def stage_candidate_opencode_free(source_home, candidate_home, candidate_home_target="/home/t3code"):
    """Stage the anonymous Zen free instance without any credential."""
    source_home = Path(source_home)
    free = Path(candidate_home) / ".config/opencode-free"
    catalog_source = source_home / ".config/opencode-free/cache/opencode/models.json"
    if catalog_source.is_symlink() or not catalog_source.is_file():
        raise RuntimeError("production anonymous Zen configuration is unavailable")
    config_target = free / "config/opencode/opencode.jsonc"
    config_target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_target.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "enabled_providers": ["opencode"],
        "provider": {"opencode": {"models": {}}},
    }, indent=2, sort_keys=True) + "\n")
    config_target.chmod(0o444)
    catalog_target = free / "cache/opencode/models.json"
    catalog_target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(catalog_source, catalog_target)
    catalog_target.chmod(0o444)
    for relative in ("data", "state"):
        (free / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
    wrapper = free / "opencode-free"
    wrapper.write_text(
        "#!/bin/sh\nset -eu\nexport OPENCODE_DISABLE_FREE_MODELS=0\n"
        f"exec {candidate_home_target}/.local/share/t3code-tools/opencode/current/bin/opencode \"$@\"\n"
    )
    wrapper.chmod(0o755)



# Exit status for a host precondition that failed before the candidate ran.
# deploy-image.sh leaves the image retryable for it; any other failure blocks
# the image.
PRECONDITION_EXIT = 75


class PreconditionError(RuntimeError):
    """A host condition checked before the candidate runs was not met."""


def stage_candidate_model_routing(source_file, candidate_tmp, candidate_uid):
    """Snapshot the live routing catalog into private candidate scratch."""
    source = Path(source_file)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
        raise PreconditionError("live model routing snapshot is unavailable")
    try:
        document = json.loads(source.read_text())
    except (OSError, ValueError):
        raise PreconditionError("live model routing snapshot is unreadable") from None
    if (not isinstance(document, dict)
            or document.get("schema") != "ghostship.ai-usage.routing"
            or document.get("schema_version") != 1
            or not isinstance(document.get("partial"), bool)):
        raise PreconditionError("live model routing snapshot is invalid")
    # The snapshot is a candidate runtime input and diagnostic evidence, not a
    # release gate: stage a partial snapshot as-is and let the real provider
    # turn decide whether the candidate can serve.
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


def verify_standalone_release(release, version, digest):
    """Compare the selected tree with its checksum-identified source archive."""
    archive = release / ".source.tar.gz"
    if archive.is_symlink() or not archive.is_file():
        raise RuntimeError("standalone T3 source archive missing")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise RuntimeError("standalone T3 archive checksum mismatch")
    marker = release / ".install-complete"
    if marker.is_symlink() or not marker.is_file() or marker.read_text().strip() != version:
        raise RuntimeError("standalone T3 installation marker mismatch")
    if not (release / "bin/t3").is_symlink() or os.readlink(release / "bin/t3") != "../t3":
        raise RuntimeError("standalone T3 launcher mismatch")

    def manifest(root, ignored=()):
        entries = {}
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if relative in ignored:
                continue
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                entries[relative] = ("link", os.readlink(path))
            elif stat.S_ISDIR(mode):
                entries[relative] = ("directory",)
            elif stat.S_ISREG(mode):
                with path.open("rb") as stream:
                    entries[relative] = ("file", mode & 0o111, hashlib.file_digest(stream, "sha256").hexdigest())
            else:
                raise RuntimeError("standalone T3 contains unsupported file")
        return entries

    try:
        with tempfile.TemporaryDirectory(prefix="t3-acceptance-source-") as temporary:
            with tarfile.open(archive, "r:gz") as payload:
                payload.extractall(temporary, filter="data")
            roots = list(Path(temporary).iterdir())
            if len(roots) != 1 or not roots[0].is_dir() or not re.fullmatch(
                    r"t3-" + re.escape(version) + r"-linux-(arm64|x64)", roots[0].name):
                raise RuntimeError("standalone T3 archive layout mismatch")
            expected = manifest(roots[0])
            actual = manifest(release, {".source.tar.gz", ".install-complete", "bin/t3"})
            if "bin" not in expected:
                actual.pop("bin", None)
            if actual != expected:
                raise RuntimeError("standalone T3 contents mismatch")
    except (OSError, tarfile.TarError) as error:
        raise RuntimeError("standalone T3 archive invalid") from error


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
    standalone = re.fullmatch(r"(\d+\.\d+\.\d+)-([0-9a-f]{64})", version)
    if not standalone and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
        raise RuntimeError("candidate T3 CLI release has an invalid version")
    t3_binary = resolve_container_home_path(
        source_home, t3_release / "bin/t3", container_home
    )
    if not t3_binary.is_file() or not os.access(t3_binary, os.X_OK):
        raise RuntimeError("candidate requires an executable installed T3 CLI")
    if standalone:
        if t3_binary != t3_release / "t3":
            raise RuntimeError("standalone T3 executable escapes its release")
        verify_standalone_release(t3_release, standalone[1], standalone[2])
    else:
        # Two layouts are valid. The managed release directory IS the runtime
        # when update-t3.py installs the whole app under t3/releases/<version>
        # and points `current` at it; older installations instead link the
        # binary into a separate .t3/runtime/versions tree. Compare resolved
        # paths on both sides: the home may itself be a symlink.
        runtime_version = t3_binary.parent
        if not valid_runtime_layout(source_home, t3_release, runtime_version):
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
    if standalone:
        verify_standalone_release(t3_destination / "releases" / version, standalone[1], standalone[2])
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


ANONYMOUS_ENV_ALLOWLIST = frozenset()
ANONYMOUS_SETTINGS_ENV_ALLOWLIST = frozenset({
    "OPENCODE_DISABLE_FREE_MODELS", "OPENCODE_MODELS_PATH",
    "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
})


def write_provider_env(source_file, target_file):
    """Write an empty candidate env; anonymous acceptance gets no credential."""
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
            if key not in ANONYMOUS_ENV_ALLOWLIST:
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
    target_file.write_text("".join(f"{key}={values[key]}\n" for key in ANONYMOUS_ENV_ALLOWLIST if key in values))
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


APP_RELEASE_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


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


def candidate_app_release(engine, name, timeout=60):
    """The T3 app release the candidate container actually serves.

    Read through the image's single selector so this code, deploy-image and the
    release window all name the app the same way. Unknown is never a pass: a
    selector that fails, or reports a release without a valid version, refuses.
    """
    result = command(engine, "exec", name, "/usr/share/t3code/served-identity.sh",
                     timeout=timeout)
    if result.returncode:
        raise PreconditionError("candidate app release is unknown")
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        raise PreconditionError("candidate app release is unreadable") from None
    served = payload.get("served") if isinstance(payload, dict) else None
    if not isinstance(served, dict):
        raise PreconditionError("candidate app release is unreadable")
    version = served.get("version")
    digest = served.get("digest") or ""
    if not isinstance(version, str) or not APP_RELEASE_PATTERN.fullmatch(version):
        raise PreconditionError("candidate app release is invalid")
    if digest and not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        raise PreconditionError("candidate app release digest is invalid")
    return f"{version}+{digest}" if digest else version


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


# Retain only route-schema fields, never arbitrary error text or credentials.
_EVIDENCE_FIELDS = frozenset({"schema", "schema_version", "partial", "generated_at", "generated_at_epoch", "max_age_seconds", "model_selection", "worker", "candidates", "coverage", "tiers", "state", "data", "selected", "pick", "provider", "provider_instance", "providerInstanceId", "instanceId", "provider_instance_id", "model", "model_id", "available", "execution", "approved_free", "native", "target", "mapped", "tool_loop", "fallback_only", "admit", "roles", "billing", "providers", "routes"})

def evidence_hash(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


_SAFE_ROUTE_VALUES = frozenset({
    "t3", "free_pool", "worker", "subscription", "free", "promotion", "ok",
    "proven", "unknown", "unavailable", "exhausted", "partial", "failed",
    "ghostship.route-policy/v2", "ghostship.model-selection/v1", "ghostship.ai-usage.routing",
    "codex", "commandCode", "opencode-free", "claudeAgent", "ollama", "google",
    "gpt-6.1-terra", "gpt-6.1-sol", "deepseek/deepseek-v4.1-flash",
    "nvidia/minimaxai/minimax-m3.1-flash",
})
_SAFE_DYNAMIC_KEYS = frozenset({"codex", "commandCode", "opencode-free", "claudeAgent",
                                "ollama", "google", "bulk", "interactive", "premium"})


def route_evidence(value, depth=0):
    if depth > 10:
        return None
    if isinstance(value, dict):
        result = {}
        for k, v in list(value.items())[:256]:
            if k not in _EVIDENCE_FIELDS:
                continue
            if k in ("providers", "tiers") and isinstance(v, dict):
                result[k] = {name: route_evidence(item, depth + 1) for name, item in list(v.items())[:128]
                             if name in _SAFE_DYNAMIC_KEYS}
            else:
                result[k] = route_evidence(v, depth + 1)
        return result
    if isinstance(value, list):
        return [route_evidence(v, depth + 1) for v in value[:128]]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        if value in _SAFE_ROUTE_VALUES:
            return value
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                return value
            except ValueError:
                pass
        return f"<redacted:{len(value)}>"
    return "<redacted>"

def capture_json_result(result):
    try:
        data = json.loads(result.stdout[:1048576])
    except (TypeError, ValueError):
        data = None
    return {"exit_code": result.returncode, "json": route_evidence(data),
            "parse_error": data is None}


FREE_LIMIT_HINTS = ("freeusagelimiterror", "free usage limit", "usage limit reached")


# A bare three-digit number in free text is not an HTTP status. Only a
# structured status or an explicit HTTP/status token counts.
STATUS_TOKEN = re.compile(r"(?:http(?:\s+status)?|status)[\"']?\s*[=:]?\s*([45]\d\d)\b", re.IGNORECASE)
OPENCODE_LOG_TAIL = 8192


def free_tier_limit(probe, extra_text=""):
    """Return a short reason when a provider turn was refused by a free-tier 429.

    The probe's bounded failure kind is often just "api-error-execution", so the
    provider's own opencode log is inspected too. A number in free text is not
    an HTTP status; only a structured status or an explicit HTTP/status token
    is. This is a classification, not a retry.
    """
    if not isinstance(probe, dict):
        probe = {}
    status = str(probe.get("error_status")) if probe.get("error_status") is not None else None
    blob = " ".join(str(probe.get(key) or "") for key in
                    ("error_type", "error_message", "detail", "failure"))
    combined = (blob + "\n" + str(extra_text or "")).lower()
    match = STATUS_TOKEN.search(blob) or STATUS_TOKEN.search(str(extra_text or ""))
    structured_status = status if status and status.startswith(("4", "5")) and len(status) == 3 else None
    if structured_status is None and match is not None:
        structured_status = match.group(1)
    limited = (structured_status == "429" or any(hint in combined for hint in FREE_LIMIT_HINTS))
    if limited:
        return f"provider free-tier limit: status={structured_status or 'unknown'}"
    return ""


def capture_opencode_log(engine, name, evidence):
    """Keep the tail of opencode's own log from the candidate before teardown.

    The provider's HTTP status and body live there when T3 only exposes a
    bounded execution kind. Bounded read; never fatal.
    """
    if evidence is None:
        return
    script = (
        "d=/home/t3code/.local/share/opencode/log; "
        "f=$(ls -t \"$d\"/*.log 2>/dev/null | head -n1); "
        "if [ -n \"$f\" ]; then tail -c " + str(OPENCODE_LOG_TAIL) + " \"$f\"; fi"
    )
    try:
        logs = command(engine, "exec", name, "sh", "-c", script, timeout=20)
        text = (logs.stdout or "") + "\n" + (logs.stderr or "")
        evidence["opencode_log_tail"] = text[-OPENCODE_LOG_TAIL:]
    except Exception:  # diagnostics must never decide the release
        evidence.setdefault("opencode_log_tail", "")


def capture_candidate_log(engine, name, evidence):
    """Keep the candidate's own log before teardown; the upstream error and the
    provider's reply are only visible there once the probe's bounded kind is
    gone. Read-only and bounded; never fatal."""
    if evidence is None:
        return
    try:
        logs = command(engine, "logs", name, timeout=20)
        text = (logs.stdout or "") + "\n" + (logs.stderr or "")
        evidence["candidate_log_tail"] = text[-4000:]
    except Exception:  # diagnostics must never decide the release
        evidence.setdefault("candidate_log_tail", "")


def check_candidate(engine, name, provider_env_file, timeout_s=300, tooling_path=None,
                    route_policy_file="/etc/ghostship/route-policy.json", routing_snapshot=None,
                    evidence=None, acceptance_route=None,
                    acceptance_route_file=None):
    if acceptance_route is None:
        if acceptance_route_file is None:
            # Never fall back to the superseded nominated primary route.
            raise PreconditionError("the acceptance route is required")
        acceptance_route = read_acceptance_route(acceptance_route_file)
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
        policy=read_route_policy(route_policy_file), snapshot=routing_snapshot, evidence=evidence,
        acceptance_route=acceptance_route,
    )
    checks["provider_turn"] = bool(provider_route)
    checks["provider_turn_route"] = provider_route
    checks["agent_cli"] = candidate_agent_command(
        engine, name, "agent", "--help"
    ).returncode == 0
    checks["skills"] = candidate_agent_command(
        engine, name, "agent", "skills", "doctor", "--json"
    ).returncode == 0
    # This only proves the local desktop CLI is present. It is not a live
    # transport proof: the anonymous candidate carries no desktop credential.
    checks["desktop_cli"] = candidate_agent_command(
        engine, name, "agent", "tools", "doctor", "--json", "--only", "ghostship-bladebro"
    ).returncode == 0
    checks["desktop_transport"] = {
        "state": "not_applicable",
        "reason": "anonymous candidate carries no desktop credential; live transport is verified after the switch by the production smoke check",
    }
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


class ProviderTurnError(RuntimeError):
    def __init__(self, pick, routes, message, detail=None):
        super().__init__(message)
        self.pick = pick
        self.routes = routes
        self.detail = detail


class RouteUnavailableError(ProviderTurnError):
    """No admitted route was proven usable; this is not an image failure."""


class RouteUnknownError(ProviderTurnError):
    """A probe may still be active and must not be replayed."""


def read_route_policy(path="/etc/ghostship/route-policy.json"):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise PreconditionError("route admission policy is unavailable") from None
    if (not isinstance(data, dict) or data.get("schema") != "ghostship.route-policy/v2"
            or not isinstance(data.get("providers"), dict) or not isinstance(data.get("routes"), list)):
        raise PreconditionError("route admission policy is invalid")
    return data


def read_acceptance_route(path=ACCEPTANCE_ROUTE_FILE):
    """Read the explicit, acceptance-only route approved by the owner."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise PreconditionError("the acceptance route is unavailable") from None
    if (not isinstance(data, dict)
            or data.get("schema") != "ghostship.t3code-acceptance-route/v1"
            or data.get("acceptance_only") is not True
            or data.get("billing") != "free"
            or data.get("provider") != T3_FREE_PROVIDER
            or (data.get("provider_instance"), data.get("model")) != ACCEPTANCE_ROUTE):
        raise PreconditionError("the acceptance route is invalid")
    return data


def admitted_acceptance_route(policy, acceptance_route=None, route=ACCEPTANCE_PRIMARY_ROUTE):
    """Return the explicit acceptance-only route, or the legacy admitted primary.

    Runtime acceptance passes the owner-approved acceptance route. The legacy
    path is retained for the existing policy-admission tests.
    """
    if acceptance_route is not None:
        if (not isinstance(acceptance_route, dict)
                or acceptance_route.get("acceptance_only") is not True
                or acceptance_route.get("billing") != "free"
                or acceptance_route.get("provider") != T3_FREE_PROVIDER
                or (acceptance_route.get("provider_instance"),
                    acceptance_route.get("model")) != ACCEPTANCE_ROUTE):
            raise PreconditionError("the acceptance route is invalid")
        effort = acceptance_route.get("effort")
        options = {"variant": effort} if isinstance(effort, str) and effort else {}
        if options and options["variant"] != ACCEPTANCE_EFFORT:
            raise PreconditionError("the acceptance route effort is invalid")
        return {"instance": ACCEPTANCE_ROUTE[0], "model": ACCEPTANCE_ROUTE[1],
                "options": options}
    if (not isinstance(policy, dict) or policy.get("schema") != "ghostship.route-policy/v2"
            or not isinstance(policy.get("providers"), dict) or not isinstance(policy.get("routes"), list)):
        raise PreconditionError("route admission policy is invalid")
    if (not isinstance(route, (tuple, list)) or len(route) != 2
            or not all(isinstance(part, str) and part for part in route)):
        raise PreconditionError("the nominated acceptance route is invalid")
    instance, model = route
    matches = []
    for item in policy["routes"]:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider")
        provider_record = policy["providers"].get(provider) if isinstance(provider, str) else None
        if (item.get("admit") is not True or item.get("fallback_only") is True
                or not isinstance(item.get("roles"), list) or "worker" not in item["roles"]
                or item.get("billing") not in ("subscription", "free", "promotion")
                or not isinstance(provider_record, dict) or provider_record.get("admit") is not True):
            continue
        if (item.get("provider_instance"), item.get("model")) == (instance, model):
            matches.append(item)
    if len(matches) != 1:
        raise PreconditionError(
            "the nominated acceptance route is not exactly one admitted worker primary"
        )
    item = matches[0]
    efforts = item.get("efforts")
    options = ({"variant": ACCEPTANCE_EFFORT}
               if isinstance(efforts, list) and ACCEPTANCE_EFFORT in efforts else {})
    return {"instance": instance, "model": model, "options": options}


def _target_identity(row):
    """The native identity a producer row names, or None."""
    if not isinstance(row, dict):
        return None
    target = row.get("target") or row.get("native") or {}
    if not isinstance(target, dict):
        return None
    return (target.get("providerInstanceId") or target.get("instanceId") or target.get("provider_instance_id"),
            target.get("model") or target.get("model_id"))


def probe_error_detail(result):
    """Retain the probe's structured failure kind without arbitrary text."""
    error = result.get("error") if isinstance(result, dict) else None
    if not isinstance(error, dict):
        return None
    fields = []
    kind = error.get("kind")
    if isinstance(kind, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", kind):
        fields.append("kind=" + kind)
    for key in ("instance", "model"):
        value = error.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:/+-]{1,200}", value):
            fields.append(f"{key}={value}")
    code = error.get("code")
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code):
        fields.append("code=" + code)
    return " ".join(fields) or None


def probe_failure_detail(failure, result):
    """Pair the computed route failure with the probe's bounded fields."""
    detail = probe_error_detail(result)
    return f"{failure}; {detail}" if detail else failure


def record_candidate_turn(evidence, payload):
    """Retain the route the candidate itself reported, never a computed one."""
    if evidence is None or not isinstance(payload, dict):
        return
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    instance = payload.get("instance")
    model = payload.get("model")
    if not isinstance(instance, str):
        instance = error.get("instance") if isinstance(error.get("instance"), str) else None
    if not isinstance(model, str):
        model = error.get("model") if isinstance(error.get("model"), str) else None
    def bounded(value, limit=256):
        return value[:limit] if isinstance(value, str) else None
    evidence["candidate_provider_turn"] = {
        "route": bounded(f"{instance}/{model}", 520) if instance and model else None,
        "instance": bounded(instance),
        "model": bounded(model),
        "outcome": bounded(payload.get("outcome"), 64),
        "settled": payload.get("settled") is True,
        "source": "candidate provider-turn-probe output",
    }


def check_provider_turn(engine, name, provider_env_file, timeout_s=300, tooling_path=None,
                        policy=None, snapshot=None, evidence=None, acceptance_route=None):
    """Prove one exact policy-admitted primary with a real turn on the candidate."""
    del provider_env_file
    if evidence is None:
        evidence = {}
    if acceptance_route is None:
        # The explicit acceptance-route file is the only runtime admission
        # input; the legacy nominated primary is not a fallback.
        raise PreconditionError("the acceptance route is required")
    policy = read_route_policy() if policy is None else policy
    diagnostics = candidate_provider_diagnostics(engine, name)
    route_result = candidate_agent_command(engine, name, "agent", "models", "--json")
    rows = []
    try:
        rows = json.loads(route_result.stdout).get("data", {}).get("selected", []) if not route_result.returncode else []
        if not isinstance(rows, list):
            rows = []
    except (ValueError, TypeError, AttributeError):
        rows = []
    if evidence is not None:
        evidence.update(model_list=capture_json_result(route_result),
                        snapshot=route_evidence(snapshot), admission=route_evidence(policy))
    route_summary = summarize_t3_rows(rows)
    if not tooling_path:
        raise RouteUnavailableError(route_summary, route_summary, "provider_turn route_unavailable: managed tools unavailable")
    target = admitted_acceptance_route(policy, acceptance_route=acceptance_route)
    identity = (target["instance"], target["model"])
    route = f"{identity[0]}/{identity[1]}"
    # A non-capacity failure is attributable to the candidate only when the
    # same route is currently proven working. Missing evidence stays unknown.
    target["proven"] = any(
        _target_identity(row) == identity
        and row.get("execution") in (None, "t3")
        and isinstance(row.get("tool_loop"), dict) and row["tool_loop"].get("state") == "proven"
        for row in rows
    )
    proof = candidate_agent_command(
        engine, name, "agent", "run", "--", "python3",
        "/run/t3code-candidate-inputs/provider-turn-probe.py", route,
        "--instance", identity[0], "--native-model", identity[1],
        "--options-json", json.dumps(target["options"], sort_keys=True),
        "--acceptance-route-json", json.dumps(acceptance_route, sort_keys=True),
        "--wait", str(min(max(timeout_s - 30, 1), 240)), timeout=min(timeout_s, 270),
    )
    if proof.returncode == 0:
        try:
            passed = json.loads(proof.stdout)
        except (ValueError, TypeError):
            passed = None
        record_candidate_turn(evidence, passed)
        if (not isinstance(passed, dict) or passed.get("outcome") != "passed"
                or passed.get("settled") is not True or passed.get("instance") != identity[0]
                or passed.get("model") != identity[1]):
            capture_candidate_log(engine, name, evidence)
            capture_opencode_log(engine, name, evidence)
            limit = free_tier_limit(passed, (evidence or {}).get("opencode_log_tail", ""))
            if limit:
                raise RouteUnavailableError(route, route_summary,
                                            f"provider_turn route_unavailable: {limit}",
                                            detail=probe_error_detail(passed))
            raise RouteUnknownError(route, route_summary,
                                    "provider_turn outcome unknown: exact settled proof is missing",
                                    detail=probe_error_detail(passed))
        return route
    category = candidate_error_category(proof)
    summary = candidate_error_summary(proof)
    failure = f"{route}:{category}-{summary}"
    try:
        result = json.loads(proof.stdout or "{}")
    except (ValueError, TypeError):
        result = {}
    record_candidate_turn(evidence, result)
    capture_candidate_log(engine, name, evidence)
    capture_opencode_log(engine, name, evidence)
    limit = free_tier_limit(result, (evidence or {}).get("opencode_log_tail", ""))
    if limit:
        raise RouteUnavailableError(route, route_summary,
                                    f"provider_turn route_unavailable: {limit}",
                                    detail=probe_failure_detail(failure, result))
    if not isinstance(result, dict) or result.get("settled") is not True:
        raise RouteUnknownError(route, route_summary,
                                "provider_turn outcome unknown: probe settlement not proven",
                                detail=probe_failure_detail(failure, result))
    code = str((result.get("error") or {}).get("code") or "") if isinstance(result.get("error"), dict) else ""
    capacity = code in ("quota", "model-unavailable", "route-unavailable", "rate_limit", "unavailable") or category == "route-unavailable"
    if capacity:
        # External availability is not a candidate regression. Retain the
        # probe's structured kind so a missing instance/auth is not hidden.
        raise RouteUnavailableError(route, route_summary,
                                    f"provider_turn route_unavailable: {failure}",
                                    detail=probe_failure_detail(failure, result))
    if not target["proven"] or code not in ("no-tool-call", "wrong-tool-result"):
        raise RouteUnknownError(route, route_summary,
                                "provider_turn outcome unknown: route failure is not attributable to the candidate",
                                detail=probe_failure_detail(failure, result))
    raise ProviderTurnError(route, route_summary,
                            f"provider_turn candidate_failed: {failure}; candidate_state={diagnostics}; route={route}",
                            detail=probe_failure_detail(failure, result))


def summarize_t3_rows(rows):
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
            f"{safe_provider}/{safe_model}:{row.get('execution') if row.get('execution') in ('t3', 'free_pool') else 'other'}:{row.get('available') is True}:{row.get('approved_free') is True}"
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


def _sha256_file(path):
    try:
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _write_report(path, document):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def read_isolation(engine, name):
    """Read the in-candidate observer; any failure is UNKNOWN."""
    result = candidate_agent_command(
        engine, name, "python3", "/run/t3code-candidate-inputs/rehearsal-isolation.py",
        timeout=30,
    )
    if result.returncode:
        return {"state": "unknown", "reason": "isolation observer failed"}
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {"state": "unknown", "reason": "isolation observer output is unreadable"}
    if (not isinstance(data, dict) or data.get("state") != "observed"
            or not data.get("env_names")):
        return {"state": "unknown", "reason": "isolation was not observed"}
    if (data.get("auth_scan") or {}).get("truncated"):
        return {**data, "state": "unknown", "reason": "the auth artifact scan was truncated"}
    if data.get("env_violations") or data.get("env_secret_names") or data.get("env_unrecognized_names"):
        names = sorted(set(data.get("env_violations") or [])
                       | set(data.get("env_secret_names") or [])
                       | set(data.get("env_unrecognized_names") or []))
        return {**data, "state": "violation",
                "reason": "environment names are not allowlisted: " + ", ".join(names[:20])}
    if data.get("auth_artifacts"):
        return {**data, "state": "violation",
                "reason": "credential-shaped files exist under HOME: "
                          + ", ".join(data["auth_artifacts"][:20])}
    if data.get("mount_violations"):
        return {**data, "state": "violation", "reason": "unexpected candidate mount"}
    if data.get("secret_names"):
        return {**data, "state": "violation",
                "reason": "credential-like names or files observed"}
    env_file = data.get("env_file") if isinstance(data.get("env_file"), dict) else {}
    if env_file.get("present") is False:
        return {**data, "state": "violation",
                "reason": "the candidate env file is absent"}
    if env_file.get("bytes") is None:
        return {**data, "state": "violation",
                "reason": "the candidate env file size is unreadable"}
    if env_file.get("bytes") != 0:
        return {**data, "state": "violation",
                "reason": "the candidate env file is not empty"}
    return data


OWNED_SCAN_DEPTH = 3
OWNED_SCAN_MAX_ENTRIES = 200000


def is_secret_artifact_name(name):
    """Secret-bearing file or directory name; never reads the content."""
    return (name in SECRET_FILE_NAMES or name == "secrets"
            or name.startswith("credentials") or name == "hosts.yml"
            or name.endswith((".key", ".pem")))


def owned_input_scan(roots, depth=OWNED_SCAN_DEPTH,
                     max_entries=OWNED_SCAN_MAX_ENTRIES):
    """Scan only the inputs this command stages or mounts from us.

    The candidate mounts the whole host store; this scan is not a store-wide
    proof and does not walk public upstream packages. Missing, dangling or
    non-directory owned roots stop the run.
    """
    findings = []
    errors = []
    paths_scanned = 0
    entries_scanned = 0
    truncated = False
    for raw in roots:
        if not raw:
            continue
        root = Path(raw)
        if root.is_symlink():
            try:
                root = root.resolve(strict=True)
            except OSError:
                errors.append(f"{raw}: owned root is a dangling symlink")
                continue
        if not root.exists():
            errors.append(f"{raw}: owned root is missing")
            continue
        if not root.is_dir():
            errors.append(f"{raw}: owned root is not a directory")
            continue
        paths_scanned += 1
        if is_secret_artifact_name(root.name):
            findings.append(str(root))
        for base, directories, files in os.walk(root, followlinks=False):
            relative_depth = len(Path(base).relative_to(root).parts)
            if relative_depth >= depth:
                directories[:] = []
            directories[:] = [name for name in directories
                              if not (Path(base) / name).is_symlink()]
            for name in list(directories) + list(files):
                entries_scanned += 1
                if entries_scanned > max_entries:
                    truncated = True
                    break
                if is_secret_artifact_name(name):
                    findings.append(str(Path(base) / name))
            if truncated:
                break
        if truncated:
            break
    return {
        "mode": "owned_inputs",
        "roots": [str(path) for path in roots if path],
        "paths_scanned": paths_scanned,
        "entries_scanned": entries_scanned,
        "depth": depth,
        "truncated": truncated,
        "errors": errors,
        "findings": sorted(set(findings)),
    }


def _nix_path_info(path):
    if not path:
        return None
    try:
        result = subprocess.run(["nix", "path-info", "-S", str(path)],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode:
        return None
    try:
        return {"path": str(path), "size_bytes": int(result.stdout.split()[1])}
    except (IndexError, ValueError, TypeError, AttributeError):
        return None


def rehearsal_outcome_for(error):
    """Classify a rehearsal exception without inventing a pass."""
    if isinstance(error, PreconditionError):
        return "precondition_not_met"
    if isinstance(error, RouteUnavailableError):
        return "route_unavailable"
    if isinstance(error, RouteUnknownError):
        return "unknown"
    if isinstance(error, ProviderTurnError):
        return "candidate_failed"
    text = str(error)
    if "teardown" in text or "production T3 identity changed" in text:
        return "unknown"
    return "failed"


REHEARSAL_EXIT_CODES = {
    "passed": 0,
    "precondition_not_met": PRECONDITION_EXIT,
    "route_unavailable": 76,
    "unknown": 77,
    "candidate_failed": 78,
    "failed": 1,
}


def rehearsal_exit_code(outcome):
    """The one exit mapping for a rehearsal report outcome."""
    return REHEARSAL_EXIT_CODES.get(outcome, 1)


def rehearsal_error_text(error):
    """Bounded, credential-safe reason for a failed rehearsal."""
    if isinstance(error, (RouteUnknownError, RouteUnavailableError, ProviderTurnError)):
        return str(error)[:2000]
    return f"{type(error).__name__}: {str(error)[:500]}"


def rehearsal_document(*, outcome, image_archive, image_id, name, tooling_path,
                       agent_revision, candidate_toolchain, checks, isolation,
                       store_scan, closure_path, build_seconds, build_source,
                       started, candidate_turn=None,
                       acceptance_route_file=ACCEPTANCE_ROUTE_FILE,
                       before=None, after=None, cleanup=None,
                       identity_unchanged=None, error=None):
    """One report shape for passed, unknown and failed rehearsals."""
    try:
        image_size = Path(image_archive).stat().st_size
    except OSError:
        image_size = None
    document = {
        "schema": REHEARSAL_SCHEMA,
        "rehearsal": True,
        "outcome": outcome,
        "image_id": image_id,
        "image_archive": str(image_archive),
        "image_size_bytes": image_size,
        "acceptance_script_sha256": _sha256_file(__file__),
        "probe_sha256": _sha256_file(Path(__file__).with_name("provider-turn-probe.py")),
        "acceptance_route_sha256": _sha256_file(acceptance_route_file),
        "tooling_path": tooling_path,
        "agent_revision": agent_revision,
        "candidate_name": name,
        "candidate_toolchain": candidate_toolchain,
        # Keep the candidate-reported route in the single provider_turn block;
        # the host-computed route string is diagnostic, not the report's quote.
        "checks": ({key: value for key, value in checks.items()
                    if key != "provider_turn_route"}
                   if isinstance(checks, dict) else checks),
        "provider_turn": {
            "route": (candidate_turn or {}).get("route"),
            "instance": (candidate_turn or {}).get("instance"),
            "model": (candidate_turn or {}).get("model"),
            "outcome": ((candidate_turn or {}).get("outcome")
                        or ("passed" if isinstance(checks, dict)
                            and checks.get("provider_turn") is True else "unknown")),
            "settled": (candidate_turn or {}).get("settled"),
            "source": (candidate_turn or {}).get("source"),
        },
        "isolation": isolation,
        "env_file_bytes": (isolation or {}).get("env_file_bytes"),
        "store_scan": store_scan,
        "store_residual": (
            "the candidate mounts the whole host /nix/store; this rehearsal "
            "scans only ghostship-owned inputs and cannot prove the store has "
            "no secret anywhere; source controls are agenix-encrypted secrets, "
            "decryption under /run, and the repository staged-diff secret scan"
        ),
        "performance": {
            "image_size_bytes": image_size,
            "closure": _nix_path_info(closure_path),
            "tooling_closure": _nix_path_info(tooling_path),
            "build_s": build_seconds,
            "build_kind": "cached_system_closure_build",
            "build_source": build_source,
            "phase_s": {"total": round(time.monotonic() - started, 3)},
        },
        "live_before": before,
        "live_after": after,
        "identity_unchanged": identity_unchanged,
        "cleanup": cleanup,
    }
    if error is not None:
        document["error"] = error
    return document


def _accept(state_dir, image_archive, podman_bin, candidate_socket, home_dir,
           volumes=(), systemctl_bin="systemctl",
           command_fn=command, identity_fn=None, candidate_uid=None,
           candidate_runtime_dir=None, provider_secrets_file=None, tooling_path=None,
           expected_agent_revision=None, candidate_home_target="/candidate-home",
           deployment_id=None, model_routing_file=None, acceptance_route_file=ACCEPTANCE_ROUTE_FILE,
           rehearsal=False, rehearsal_report=None, closure_path=None, build_seconds=None,
           build_source=None, _evidence=None):
    """Boot, check, record and remove one candidate without changing production."""
    identity_fn = identity_fn or _probe.identity
    candidate_uid = os.getuid() if candidate_uid is None else int(candidate_uid)
    validated_volumes = validate_candidate_mounts(volumes)
    approved_workers_file = next(
        (str(volume).split(":", 2)[0] for volume in validated_volumes
         if str(volume).split(":", 2)[1:2] == ["/etc/ghostship/approved-free-workers.json"]),
        None,
    )
    route_policy_file = next(
        (str(volume).split(":", 2)[0] for volume in validated_volumes
         if str(volume).split(":", 2)[1:2] == ["/etc/ghostship/route-policy.json"]),
        "/etc/ghostship/route-policy.json",
    )
    state_dir = Path(state_dir)
    desired = deployment_id or (state_dir / "desired").read_text().strip()
    image_id, image_tag = image_details(image_archive)
    _evidence["candidate"]["image_id"] = image_id
    name = candidate_name(desired)
    receipts = state_dir / "receipts"
    receipt_path = None if rehearsal else receipts / f"{desired}.json"
    if receipt_path is not None:
        receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
        receipt_path.unlink(missing_ok=True)
    started = time.monotonic()
    before = identity_fn()
    _evidence["live_before"] = before
    if rehearsal and not closure_path:
        raise PreconditionError("the store closure is required")
    store_scan = (owned_input_scan([tooling_path, str(Path(__file__).parent)])
                  if rehearsal else None)
    if rehearsal:
        _evidence["store_scan"] = store_scan
        if store_scan["findings"]:
            raise PreconditionError("the owned input scan found a secret-bearing path")
        if (store_scan["errors"] or store_scan["truncated"]
                or not store_scan["paths_scanned"]):
            raise PreconditionError("the owned input scan could not cover its roots")
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
    evidence = _evidence
    report_args = None
    report_document = None
    try:
        staged_toolchain = stage_candidate_inputs(
            home_dir, home_copy, input_copy, candidate_uid, tooling_path,
            candidate_home_target, stage_toolchain=bool(tooling_path),
            approved_free_workers_file=approved_workers_file,
        )
        write_provider_env(None if rehearsal else provider_secrets_file, provider_env)
        os.chown(provider_env, candidate_uid, candidate_uid)
        if rehearsal or tooling_path:
            assert_candidate_auth_free(
                home_copy, input_copy, provider_env,
                allow_missing_settings=bool(rehearsal and not tooling_path))
        if model_routing_file:
            try:
                source = Path(model_routing_file)
                if not source.is_symlink() and source.stat().st_size <= 16 * 1024 * 1024:
                    evidence["snapshot"] = route_evidence(json.loads(source.read_text()))
            except (OSError, ValueError):
                evidence["snapshot"] = None
        try:
            evidence["admission"] = route_evidence(read_route_policy(route_policy_file))
        except PreconditionError:
            evidence["admission"] = None
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
        routing_snapshot = json.loads(routing_copy.read_text()) if routing_copy else None
        checks = check_candidate(engine, name, provider_env, tooling_path=tooling_path,
                                 route_policy_file=route_policy_file, routing_snapshot=routing_snapshot,
                                 evidence=evidence, acceptance_route_file=acceptance_route_file)
        evidence["rehearsal_checks"] = checks
        agent_path = candidate_agent_path(engine, name, candidate_home_target)
        if rehearsal:
            if not agent_path:
                store_scan["errors"].append("resolved agent path is missing")
                _evidence["store_scan"] = store_scan
                raise RuntimeError(
                    "candidate owned input scan failed after start: "
                    "resolved agent path is missing")
            resolved_agent = Path(agent_path).resolve()
            resolved_tooling = (Path(tooling_path).resolve()
                                if tooling_path else None)
            inside_tooling = bool(resolved_tooling) and (
                resolved_agent == resolved_tooling
                or resolved_tooling in resolved_agent.parents)
            if inside_tooling:
                store_scan["agent_path_owner"] = str(resolved_tooling)
                store_scan["agent_path_inside_tooling"] = True
            elif str(resolved_agent) in {str(Path(root).resolve())
                                         for root in store_scan["roots"] if root}:
                store_scan["agent_path_owner"] = str(resolved_agent)
                store_scan["agent_path_inside_tooling"] = False
            else:
                agent_scan = owned_input_scan([str(resolved_agent)])
                store_scan["agent_path_owner"] = str(resolved_agent)
                store_scan["agent_path_inside_tooling"] = False
                for key in ("findings", "errors"):
                    store_scan[key] = sorted(set(store_scan[key]) | set(agent_scan[key]))
                store_scan["paths_scanned"] += agent_scan["paths_scanned"]
                store_scan["entries_scanned"] += agent_scan["entries_scanned"]
                store_scan["truncated"] = (store_scan["truncated"]
                                           or agent_scan["truncated"])
            _evidence["store_scan"] = store_scan
            if store_scan["findings"]:
                raise RuntimeError(
                    "candidate owned input scan failed after start: "
                    "an owned root carries a secret-bearing path")
            if store_scan["errors"] or store_scan["truncated"]:
                raise RuntimeError(
                    "candidate owned input scan failed after start: "
                    "an owned root is missing, dangling or truncated")
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
        if rehearsal:
            isolation = read_isolation(engine, name)
            outcome = ("passed" if isolation.get("state") == "observed"
                       else "unknown")
            report_args = {
                "image_archive": image_archive, "image_id": image_id,
                "name": name, "tooling_path": tooling_path,
                "agent_revision": expected_agent_revision,
                "candidate_toolchain": staged_toolchain, "checks": checks,
                "isolation": isolation, "store_scan": _evidence.get("store_scan"),
                "closure_path": closure_path, "build_seconds": build_seconds,
                "build_source": build_source, "started": started,
                "candidate_turn": _evidence.get("candidate_provider_turn"),
                "acceptance_route_file": acceptance_route_file,
                "before": before,
            }
            # Written after teardown, with the observed post-teardown identity.
            report_document = rehearsal_document(
                outcome=outcome, after=None, cleanup=None,
                identity_unchanged=None, **report_args)
        else:
            app_release = candidate_app_release(command_fn, name)
            receipt = {
                "deployment_id": desired,
                "image_id": image_id,
                "app_release": app_release,
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
        cleanup_record = {
            "container_created": created,
            "container_removed": None,
            "manager_started": manager_started,
            "manager_stopped": None,
            "workspace_removed": False,
            "error": None,
        }
        if created:
            removed = command_fn(engine, "rm", "--force", "--time", "10", name, timeout=30)
            cleanup_record["container_removed"] = removed.returncode == 0
            if removed.returncode:
                cleanup_error = "candidate container teardown failed"
        if manager_started:
            try:
                subprocess.run([systemctl_bin, "stop", "t3code-podman-candidate.service"],
                               check=True, timeout=30)
                cleanup_record["manager_stopped"] = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                cleanup_record["manager_stopped"] = False
                cleanup_error = "candidate Podman manager teardown failed"
        try:
            remove_candidate_workspace(candidate_tmp)
        except OSError:
            cleanup_error = "candidate acceptance workspace teardown failed"
        cleanup_record["workspace_removed"] = not candidate_tmp.exists()
        if candidate_tmp.exists():
            cleanup_error = "candidate acceptance workspace teardown failed"
        try:
            after = identity_fn()
        except Exception:
            after = None
            cleanup_error = "production T3 identity could not be observed after teardown"
        cleanup_record["error"] = cleanup_error
        _evidence["cleanup"] = cleanup_record
        _evidence["live_after"] = after
        _evidence["identity_unchanged"] = before == after
        if receipt_path is not None and (before != after or cleanup_error):
            receipt_path.unlink(missing_ok=True)
        if report_args is not None and report_document is not None:
            final_outcome = report_document.get("outcome", "unknown")
            if cleanup_error or before != after:
                final_outcome = "unknown"
            report_document = rehearsal_document(
                outcome=final_outcome, after=after,
                cleanup=cleanup_record, identity_unchanged=before == after,
                **report_args)
            try:
                _write_report(
                    Path(rehearsal_report or (Path(state_dir) / "rehearsal.json")),
                    report_document)
            except OSError as report_error:
                print(f"candidate rehearsal report could not be written: {report_error}",
                      file=sys.stderr)
        if cleanup_error:
            raise RuntimeError(cleanup_error)
        if before != after:
            raise RuntimeError("production T3 identity changed during candidate teardown")
    if rehearsal and report_document is not None:
        return report_document
    return None


def safe_unknown_evidence(error):
    message = str(error)
    known = ("exact settled proof is missing", "probe settlement not proven",
             "route failure is not attributable to the candidate")
    for reason in known:
        if message == "provider_turn outcome unknown: " + reason:
            return message
    return "provider_turn outcome unknown"


def _write_failed_rehearsal(state, image_archive, kwargs, desired, evidence, started, error):
    """Write the failed/UNKNOWN rehearsal report and re-raise the failure."""
    report_path = Path(kwargs.get("rehearsal_report") or (state / "rehearsal.json"))
    isolation = {"state": "unknown",
                 "reason": "rehearsal failed before a successful isolation observation"}
    try:
        existing = json.loads(report_path.read_text())
    except (OSError, ValueError):
        existing = None
    if isinstance(existing, dict) and isinstance(existing.get("isolation"), dict):
        isolation = existing["isolation"]
        if existing.get("outcome") == "passed":
            isolation = {**isolation, "state": "unknown",
                         "reason": "performed with a failed teardown"}
    document = rehearsal_document(
        outcome=rehearsal_outcome_for(error), image_archive=image_archive,
        image_id=evidence.get("candidate", {}).get("image_id"),
        name=desired, tooling_path=kwargs.get("tooling_path"),
        agent_revision=kwargs.get("expected_agent_revision"),
        candidate_toolchain=None, checks=evidence.get("rehearsal_checks") or {},
        isolation=isolation, store_scan=evidence.get("store_scan"),
        closure_path=kwargs.get("closure_path"),
        build_seconds=kwargs.get("build_seconds"),
        build_source=kwargs.get("build_source"), started=started,
        candidate_turn=evidence.get("candidate_provider_turn"),
        acceptance_route_file=kwargs.get("acceptance_route_file", ACCEPTANCE_ROUTE_FILE),
        before=(existing.get("live_before") if isinstance(existing, dict)
                else evidence.get("live_before")),
        after=evidence.get("live_after"), cleanup=evidence.get("cleanup"),
        identity_unchanged=evidence.get("identity_unchanged"),
        error=rehearsal_error_text(error),
    )
    try:
        _write_report(report_path, document)
    except OSError as report_error:
        print(f"candidate rehearsal report could not be written: {report_error}",
              file=sys.stderr)
    raise


def accept(state_dir, image_archive, podman_bin, candidate_socket, home_dir, *args, **kwargs):
    """Capture best-effort evidence for every failure, including setup and teardown."""
    state = Path(state_dir)
    rehearsal = kwargs.get("rehearsal") is True
    started = time.monotonic()
    safe_desired = "unknown"
    evidence = {"candidate": {"deployment_id": safe_desired, "image_id": None}}
    try:
        desired = kwargs.get("deployment_id")
        if rehearsal and desired is None:
            # A rehearsal names no deployment: bind the scratch candidate to
            # the built archive under test instead of reading deploy state.
            digest = _sha256_file(image_archive) or "unknown"
            desired = "rehearsal-" + digest.split(":", 1)[-1][:12]
        if desired is None:
            try:
                desired = (state / "desired").read_text().strip()
            except OSError:
                desired = None
        if rehearsal:
            safe_desired = (desired if isinstance(desired, str)
                            and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", desired)
                            else "unknown")
            if kwargs.get("deployment_id") is None:
                kwargs["deployment_id"] = safe_desired
        else:
            safe_desired = desired if isinstance(desired, str) and re.fullmatch(r"(?:[0-9a-f]{64}|generation-[0-9]+)", desired) else "unknown"
        evidence["candidate"]["deployment_id"] = safe_desired
        return _accept(state_dir, image_archive, podman_bin, candidate_socket, home_dir,
                       *args, _evidence=evidence, **kwargs)
    except Exception as error:
        if rehearsal:
            # No deploy state is written by a rehearsal: the report is the
            # only record, and it must not claim a pass that was not observed.
            return _write_failed_rehearsal(
                state, image_archive, kwargs, safe_desired, evidence, started, error)
        try:
            attempts = Path(state_dir) / "attempts"
            attempts.mkdir(mode=0o700, parents=True, exist_ok=True)
            attempt = attempts / f"{safe_desired}.json"
            try:
                record = json.loads(attempt.read_text())
                if not isinstance(record, dict):
                    record = {}
            except (OSError, ValueError):
                record = {}
            if isinstance(error, ProviderTurnError):
                # Provider-provided strings can contain arbitrary credentials.
                # Only the structured kind/identity from the probe is retained.
                if isinstance(error, RouteUnknownError):
                    evidence_text = safe_unknown_evidence(error)
                    if error.detail:
                        evidence_text += "; " + error.detail
                elif isinstance(error, RouteUnavailableError):
                    evidence_text = "route_unavailable"
                    if error.detail:
                        evidence_text += ": " + error.detail
                    elif "quota" in str(error).lower():
                        evidence_text += ": quota"
                else:
                    evidence_text = "provider route failure"
                    if error.detail:
                        evidence_text += ": " + error.detail
                record["provider_turn"] = {"pick": evidence_hash(error.pick),
                                           "routes": evidence_hash(error.routes),
                                           "evidence": evidence_text}
            evidence["incomplete"] = safe_unknown_evidence(error) if isinstance(error, RouteUnknownError) else None
            if isinstance(error, RouteUnknownError) and error.detail:
                evidence["incomplete"] = (evidence["incomplete"] or "") + "; " + error.detail
            if len(json.dumps(evidence)) > 131072:
                evidence = {"candidate": evidence["candidate"], "incomplete": evidence.get("incomplete"),
                            "truncated": True, "reason": "route provenance exceeds 128 KiB"}
            record["route_provenance"] = evidence
            if isinstance(error, RouteUnavailableError):
                record["outcome"] = "route_unavailable"
            elif isinstance(error, RouteUnknownError):
                record["outcome"] = "route_unknown"
            temporary = attempt.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record, sort_keys=True) + "\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, attempt)
        except (OSError, ValueError, TypeError):
            print("candidate acceptance provenance could not be recorded", file=sys.stderr)
        raise


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
    parser.add_argument("--acceptance-route-file", default=ACCEPTANCE_ROUTE_FILE)
    parser.add_argument("--volume", action="append", default=[])
    parser.add_argument("--systemctl-bin", default="systemctl")
    parser.add_argument("--candidate-uid", type=int, required=True)
    parser.add_argument("--rehearsal", action="store_true",
                        help="boot, check and remove one candidate without a window, switch or receipt")
    parser.add_argument("--rehearsal-report",
                        help="report path (default <state-dir>/rehearsal.json)")
    parser.add_argument("--closure-path",
                        help="built system closure under test, for the #725 closure size")
    parser.add_argument("--build-seconds", type=float,
                        help="duration measured by the release build log")
    parser.add_argument("--build-source",
                        help="log path, line or URL the build duration came from")
    args = parser.parse_args()
    if args.rehearsal and args.provider_secrets_file:
        print("candidate rehearsal never reads a provider secrets file", file=sys.stderr)
        sys.exit(PRECONDITION_EXIT)
    if args.rehearsal and not args.closure_path:
        print("candidate rehearsal requires --closure-path for the #725 closure size", file=sys.stderr)
        sys.exit(PRECONDITION_EXIT)
    if args.build_seconds is not None and (args.build_seconds < 0
                                           or args.build_seconds != args.build_seconds):
        print("--build-seconds must be a measured non-negative duration", file=sys.stderr)
        sys.exit(PRECONDITION_EXIT)
    try:
        result = accept(args.state_dir, args.image_archive, args.podman_bin, args.candidate_socket,
               args.home_dir, args.volume, args.systemctl_bin,
               candidate_uid=args.candidate_uid,
               candidate_runtime_dir=args.candidate_runtime_dir,
               provider_secrets_file=args.provider_secrets_file,
               tooling_path=args.tooling_path,
               expected_agent_revision=args.agent_revision,
               candidate_home_target=args.candidate_home_target,
               model_routing_file=args.model_routing_file,
               acceptance_route_file=args.acceptance_route_file,
               rehearsal=args.rehearsal,
               rehearsal_report=args.rehearsal_report,
               closure_path=args.closure_path,
               build_seconds=args.build_seconds,
               build_source=args.build_source)
    except PreconditionError as error:
        print(f"candidate acceptance precondition not met: {error}", file=sys.stderr)
        sys.exit(PRECONDITION_EXIT)
    except RouteUnavailableError as error:
        print(f"candidate acceptance route_unavailable: {error}", file=sys.stderr)
        sys.exit(76)
    except RouteUnknownError as error:
        print(f"candidate acceptance route_unknown: {error}", file=sys.stderr)
        sys.exit(77)
    except ProviderTurnError as error:
        print(f"candidate acceptance candidate_failed: {error}", file=sys.stderr)
        sys.exit(78)
    if isinstance(result, dict) and result.get("rehearsal") is True:
        raise SystemExit(rehearsal_exit_code(result.get("outcome")))


if __name__ == "__main__":
    main()
