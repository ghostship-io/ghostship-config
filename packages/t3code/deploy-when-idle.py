"""Deploy changed T3 Code container images after exact-image candidate acceptance."""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tarfile
from datetime import datetime, timezone

# The host stamps each container with the image deployment it was created from.
DEPLOYMENT_LABEL = "io.ghostship.t3code.deployment"
# Container tool maintenance holds this lock; the home bind mount shares it.
TOOL_LOCK = Path(".local/state/t3code-tool-update/tool-update.lock")
# Restarting cannot repair a broken image; stop after this many failed starts.
MAX_DEPLOY_ATTEMPTS = 3
# The ledger of restarts performed after candidate image acceptance.
RESTART_LEDGER = "/var/lib/t3code-restarts/ledger.jsonl"


def live_agent_path(podman_bin, container_home="/candidate-home"):
    try:
        result = subprocess.run(
            [podman_bin, "exec", "t3code", "readlink", "-f",
             f"{container_home}/.local/state/ghostship-t3-tools/current"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def live_secret_inode(podman_bin):
    try:
        result = subprocess.run(
            [podman_bin, "exec", "t3code", "stat", "-Lc", "%i", "/run/secrets/t3code.env"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def live_inputs_match(podman_bin, expected_agent_path=None, provider_secrets_file=None,
                      container_home="/candidate-home"):
    if expected_agent_path and live_agent_path(podman_bin, container_home) != str(Path(expected_agent_path).resolve()):
        return False
    if provider_secrets_file:
        try:
            expected_inode = str(Path(provider_secrets_file).stat().st_ino)
        except OSError:
            return False
        if live_secret_inode(podman_bin) != expected_inode:
            return False
    return True


def write_live_inputs_receipt(state_dir, podman_bin, deployment_id,
                              expected_agent_revision=None, tooling_path=None,
                              provider_secrets_file=None, container_home="/candidate-home"):
    if not (expected_agent_revision or tooling_path or provider_secrets_file):
        return
    agent_path = live_agent_path(podman_bin, container_home) if tooling_path else ""
    secret_inode = live_secret_inode(podman_bin) if provider_secrets_file else ""
    if not live_inputs_match(podman_bin, tooling_path, provider_secrets_file, container_home):
        raise RuntimeError("live T3 inputs do not match the accepted deployment")
    receipt = {
        "deployment_id": deployment_id,
        "agent_revision": expected_agent_revision,
        "agent_path": agent_path,
        "provider_secret_inode": secret_inode,
        "verified": True,
        "verified_at": utcnow_iso(),
    }
    target = Path(state_dir) / "deployed-inputs.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def require_candidate(state_dir, image_archive, podman_bin, expected_agent_revision=None,
                      provider_secrets_file=None, tooling_path=None,
                      container_home="/candidate-home", deployment_id=None):
    """An owner request bypasses idle, never candidate acceptance."""
    if not image_archive:
        raise RuntimeError("image archive missing; refusing an unverified image change")
    with tarfile.open(image_archive) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        config = archive.extractfile(manifest[0]["Config"]).read()
    image_id = hashlib.sha256(config).hexdigest()
    running = container_identity(podman_bin)
    state_dir = Path(state_dir)
    desired = deployment_id or (state_dir / "desired").read_text().strip()
    current = running.get("image", "").removeprefix("sha256:")
    expected_secret_inode = None
    if provider_secrets_file:
        try:
            expected_secret_inode = str(Path(provider_secrets_file).stat().st_ino)
        except OSError:
            raise RuntimeError("candidate provider projection is missing") from None
    if (current == image_id and running.get("deployment") == desired
            and live_inputs_match(podman_bin, tooling_path, provider_secrets_file, container_home)):
        return
    receipt_path = state_dir / "receipts" / f"{desired}.json"
    try:
        receipt = json.loads(receipt_path.read_text())
    except FileNotFoundError:
        raise RuntimeError(
            f"candidate receipt missing for desired deployment {desired}: {receipt_path}"
        ) from None
    checks = ("app_ready", "provider_turn", "agent_cli", "skills", "desktop_transport")
    if not (
        receipt.get("deployment_id") == desired
        and receipt.get("image_id", "").removeprefix("sha256:") == image_id
        and receipt.get("candidate_name", "").startswith("t3code-candidate-")
        and receipt.get("live_before") and receipt.get("live_before") == receipt.get("live_after")
        and (expected_agent_revision is None or receipt.get("agent_revision") == expected_agent_revision)
        and (tooling_path is None or receipt.get("agent_path") == str(Path(tooling_path).resolve()))
        and (expected_secret_inode is None or receipt.get("provider_secret_inode") == expected_secret_inode)
        and all(receipt.get("checks", {}).get(name) is True for name in checks)
    ):
        raise RuntimeError("candidate receipt does not approve this exact T3 image")


def verify_candidate_receipt(state_dir, image_archive, deployment_id,
                             expected_agent_revision=None, provider_secrets_file=None,
                             tooling_path=None, candidate_home_target="/candidate-home"):
    """Return the passing receipt only when it approves this exact built image."""
    if not deployment_id or not image_archive:
        raise RuntimeError("candidate deployment ID or image archive is missing")
    with tarfile.open(image_archive) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        config = archive.extractfile(manifest[0]["Config"]).read()
    image_id = hashlib.sha256(config).hexdigest()
    receipt_path = Path(state_dir) / "receipts" / f"{deployment_id}.json"
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError):
        raise RuntimeError("candidate acceptance receipt is missing or invalid") from None
    expected_inode = None
    if provider_secrets_file:
        try:
            expected_inode = str(Path(provider_secrets_file).stat().st_ino)
        except OSError:
            raise RuntimeError("candidate provider projection is missing") from None
    checks = ("app_ready", "provider_turn", "agent_cli", "skills", "desktop_transport")
    approved = (
        receipt.get("deployment_id") == deployment_id
        and receipt.get("image_id", "").removeprefix("sha256:") == image_id
        and receipt.get("candidate_name", "").startswith("t3code-candidate-")
        and bool(receipt.get("live_before"))
        and receipt.get("live_before") == receipt.get("live_after")
        and (expected_agent_revision is None or receipt.get("agent_revision") == expected_agent_revision)
        and (tooling_path is None or receipt.get("agent_path") == str(Path(tooling_path).resolve()))
        and (expected_inode is None or receipt.get("provider_secret_inode") == expected_inode)
        and all(receipt.get("checks", {}).get(name) is True for name in checks)
    )
    if not approved:
        raise RuntimeError("candidate receipt does not approve this exact T3 image")
    return {**receipt, "verified": True}


def produce_candidate_receipt(state_dir, image_archive, podman_bin, candidate_socket,
                             home_dir, volumes=(), candidate_uid=62041,
                             candidate_runtime_dir="/var/lib/t3code-podman-candidate/acceptance",
                             provider_secrets_file=None, tooling_path=None,
                             expected_agent_revision=None,
                             candidate_home_target="/candidate-home", deployment_id=None,
                             force_test=False):
    """Run acceptance once when the desired image has no approved receipt."""
    if not force_test:
        try:
            require_candidate(state_dir, image_archive, podman_bin, expected_agent_revision,
                              provider_secrets_file, tooling_path, candidate_home_target, deployment_id)
            return
        except RuntimeError:
            pass
    script = Path(__file__).with_name("candidate-acceptance.py")
    spec = importlib.util.spec_from_file_location("t3code_candidate_acceptance", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.accept(
        state_dir, image_archive, podman_bin, candidate_socket, home_dir,
        volumes,
        candidate_uid=candidate_uid,
        candidate_runtime_dir=candidate_runtime_dir,
        provider_secrets_file=provider_secrets_file,
        tooling_path=tooling_path,
        expected_agent_revision=expected_agent_revision,
        candidate_home_target=candidate_home_target,
        deployment_id=deployment_id,
    )
    require_candidate(state_dir, image_archive, podman_bin, expected_agent_revision,
                      provider_secrets_file, tooling_path, candidate_home_target, deployment_id)


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(audit_log, message):
    ts = utcnow_iso()
    line = f"{ts} info: {message}"
    print(line, flush=True)
    if audit_log:
        try:
            audit_log.parent.mkdir(parents=True, exist_ok=True)
            with audit_log.open("a", encoding="utf-8") as f:
                f.write(f"{ts} source=host-deployment {message}\n")
        except Exception as e:
            print(f"{ts} warn: failed writing audit log: {e}", file=sys.stderr)


def acquire_tool_lock(home_dir):
    """Hold the container tool-maintenance lock across a container restart.

    Returns an open descriptor, None when the container predates the shared
    lock, or False when tool maintenance currently holds it.
    """
    tool_lock = Path(home_dir) / TOOL_LOCK
    if not tool_lock.parent.is_dir():
        return None
    fd = os.open(str(tool_lock), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        return False
    return fd


def release_tool_lock(fd):
    if fd in (None, False):
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def running_deployment(podman_bin):
    """Return the deployment ID the running container was created from."""
    try:
        res = subprocess.run(
            [
                podman_bin,
                "inspect",
                "t3code",
                "--format",
                '{{ index .Config.Labels "' + DEPLOYMENT_LABEL + '" }}',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if res.returncode != 0:
        return ""
    value = res.stdout.strip()
    return "" if value == "<no value>" else value


def health_state(podman_bin):
    """Return "healthy", "starting", or "unhealthy" for the running container.

    Inspection errors report "starting" so a transient Podman failure is never
    counted as a failed deployment.
    """
    try:
        inspect_proc = subprocess.run(
            [podman_bin, "inspect", "t3code", "--format", "{{.State.Health.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return "starting"
    if inspect_proc.returncode != 0:
        return "starting"
    status = inspect_proc.stdout.strip()
    if status == "starting":
        return "starting"
    if status != "healthy":
        return "unhealthy"
    try:
        srv_proc = subprocess.run(
            [podman_bin, "exec", "t3code", "systemctl", "is-active", "--quiet", "t3code-server.service"],
            timeout=10,
        )
        curl_proc = subprocess.run(
            [podman_bin, "exec", "t3code", "curl", "-fsS", "--max-time", "5", "http://127.0.0.1:3773/"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        return "starting"
    if srv_proc.returncode == 0 and curl_proc.returncode == 0:
        return "healthy"
    return "unhealthy"


def wait_healthy(podman_bin, timeout_seconds=120):
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        if health_state(podman_bin) == "healthy":
            return True
        time.sleep(5)
    return False


def read_failures(failures_file, desired):
    """Return failed start attempts recorded for this deployment ID."""
    try:
        recorded, count = failures_file.read_text().split()
        return int(count) if recorded == desired else 0
    except (OSError, ValueError):
        return 0


def run_deployment(
    state_dir,
    home_dir,
    podman_bin="podman",
    systemctl_bin="systemctl",
    audit_log=None,
    health_timeout_seconds=120,
    healthy_waiter=None,
    deployment_reader=None,
    tool_lock_acquirer=None,
    health_reader=None,
    max_attempts=MAX_DEPLOY_ATTEMPTS,
    image_archive=None,
    candidate_socket="/run/t3code-podman-candidate/podman.sock",
    volumes=(),
    candidate_acceptor=produce_candidate_receipt,
    candidate_uid=62041,
    candidate_runtime_dir="/var/lib/t3code-podman-candidate/acceptance",
    provider_secrets_file=None,
    tooling_path=None,
    expected_agent_revision=None,
    candidate_home_target="/candidate-home",
):
    state_dir = Path(state_dir)
    home_dir = Path(home_dir)
    desired_file = state_dir / "desired"
    applied_file = state_dir / "applied"
    applying_file = state_dir / "applying"
    pending_file = state_dir / "restart.pending"
    failures_file = state_dir / "failures"
    desired_inputs_file = state_dir / "desired-inputs"
    applied_inputs_file = state_dir / "applied-inputs"

    state_dir.mkdir(parents=True, exist_ok=True)

    lock_file = state_dir / "deploy.lock"
    lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(lock_fd)
        return 0

    try:
        desired = desired_file.read_text().strip() if desired_file.is_file() else ""
        applied = applied_file.read_text().strip() if applied_file.is_file() else ""
        applying = applying_file.read_text().strip() if applying_file.is_file() else ""
        restart_pending = pending_file.is_file()
        desired_inputs = desired_inputs_file.read_text().strip() if desired_inputs_file.is_file() else ""
        applied_inputs = applied_inputs_file.read_text().strip() if applied_inputs_file.is_file() else ""
        inputs_changed = desired_inputs != applied_inputs

        if not restart_pending and (not desired or (desired == applied and not inputs_changed)):
            return 0

        if desired and image_archive and candidate_acceptor:
            candidate_acceptor(
                state_dir, image_archive, podman_bin, candidate_socket, home_dir,
                volumes,
                candidate_uid,
                candidate_runtime_dir,
                provider_secrets_file,
                tooling_path,
                expected_agent_revision,
                candidate_home_target,
            )

        # A reboot, an interrupted deploy, or a slow health check can leave the
        # desired image already running. Record it once it is healthy instead
        # of restarting again; retry an unhealthy one a bounded number of times.
        read_deployment = deployment_reader or (lambda: running_deployment(podman_bin))
        read_health = health_reader or (lambda: health_state(podman_bin))
        if (desired and desired == applied and inputs_changed and not restart_pending
                and (tooling_path or provider_secrets_file)
                and read_deployment() == desired
                and live_inputs_match(podman_bin, tooling_path, provider_secrets_file,
                                      candidate_home_target)):
            tmp_inputs = state_dir / "applied-inputs.tmp"
            tmp_inputs.write_text(desired_inputs + "\n")
            tmp_inputs.replace(applied_inputs_file)
            write_live_inputs_receipt(
                state_dir, podman_bin, desired, expected_agent_revision,
                tooling_path, provider_secrets_file, candidate_home_target,
            )
            return 0
        retry_unhealthy = False
        if desired and desired != applied and not restart_pending:
            if read_deployment() == desired:
                state = read_health()
                if state == "starting":
                    return 0
                if state == "healthy" and live_inputs_match(
                        podman_bin, tooling_path, provider_secrets_file, candidate_home_target):
                    tmp_applied = state_dir / "applied.tmp"
                    tmp_applied.write_text(desired)
                    tmp_applied.replace(applied_file)
                    if desired_inputs:
                        tmp_inputs = state_dir / "applied-inputs.tmp"
                        tmp_inputs.write_text(desired_inputs + "\n")
                        tmp_inputs.replace(applied_inputs_file)
                    write_live_inputs_receipt(
                        state_dir, podman_bin, desired, expected_agent_revision,
                        tooling_path, provider_secrets_file, candidate_home_target,
                    )
                    for stale in (applying_file, failures_file):
                        if stale.exists():
                            stale.unlink()
                    log(audit_log, f"action=adopt-running desired={desired}")
                    return 0
                retry_unhealthy = True
            # Whether the broken image is running, exited, or never replaced
            # the old one, stop once it has failed enough; wait for a new image.
            if read_failures(failures_file, desired) >= max_attempts:
                return 0

        wait_for_health = healthy_waiter or (
            lambda: wait_healthy(podman_bin, timeout_seconds=health_timeout_seconds)
        )

        # Only a stopped or failed unit may restart directly. A unit mid-start
        # or mid-stop belongs to another restart; restarting it
        # again kills the container it is bringing up.
        try:
            res = subprocess.run(
                [systemctl_bin, "is-active", "podman-t3code.service"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            log(audit_log, f"action=defer desired={desired} restart_pending={restart_pending} reason=unit-state-unknown")
            return 0
        is_active = res.returncode == 0
        if not is_active and (res.stdout or "").strip() not in ("inactive", "failed"):
            log(audit_log, f"action=defer desired={desired} restart_pending={restart_pending} reason=unit-transitioning")
            return 0

        if is_active:
            log(audit_log, f"action=candidate-accepted desired={desired} restart_pending={restart_pending}")

        # Keep container tool maintenance from starting between the idle
        # check and the restart, and never restart in the middle of it.
        tool_lock = (tool_lock_acquirer or (lambda: acquire_tool_lock(home_dir)))()
        if tool_lock is False:
            log(audit_log, f"action=defer desired={desired} restart_pending={restart_pending} reason=tool-maintenance")
            return 0

        try:
            require_candidate(state_dir, image_archive, podman_bin, expected_agent_revision,
                              provider_secrets_file, tooling_path, candidate_home_target)
            if desired:
                tmp_applying = state_dir / "applying.tmp"
                tmp_applying.write_text(desired)
                tmp_applying.replace(applying_file)

            log(audit_log, f"action=restart-container desired={desired} restart_pending={restart_pending}")
            try:
                subprocess.run([systemctl_bin, "restart", "podman-t3code.service"], check=True, timeout=300)
                restarted = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                restarted = False
        finally:
            release_tool_lock(tool_lock)

        healthy = restarted and wait_for_health()
        inputs_match = healthy and live_inputs_match(
            podman_bin, tooling_path, provider_secrets_file, candidate_home_target)
        if not healthy or not inputs_match:
            failures = read_failures(failures_file, desired) + 1
            tmp_failures = state_dir / "failures.tmp"
            tmp_failures.write_text(f"{desired} {failures}\n")
            tmp_failures.replace(failures_file)
            log(audit_log, f"action=deployment-failed desired={desired} attempt={failures}/{max_attempts}")
            if failures == max_attempts:
                # Drop a requested restart too; a new request retries once.
                if pending_file.exists():
                    pending_file.unlink()
                log(audit_log, f"action=deployment-abandoned desired={desired} reason=unhealthy-after-{failures}-attempts")
            return 1
        write_live_inputs_receipt(
            state_dir, podman_bin, desired, expected_agent_revision,
            tooling_path, provider_secrets_file, candidate_home_target,
        )

        if desired:
            tmp_applied = state_dir / "applied.tmp"
            tmp_applied.write_text(desired)
            tmp_applied.replace(applied_file)
        if desired_inputs:
            tmp_inputs = state_dir / "applied-inputs.tmp"
            tmp_inputs.write_text(desired_inputs + "\n")
            tmp_inputs.replace(applied_inputs_file)

        for done in (applying_file, pending_file, failures_file):
            if done.exists():
                done.unlink()

        log(audit_log, f"action=deployment-complete desired={desired}")
        return 0
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except OSError:
            pass


def actor():
    """Who asked for a restart, for the ledger."""
    return {
        "user": os.environ.get("USER") or os.environ.get("LOGNAME") or "",
        "uid": os.getuid(),
        "host": os.uname().nodename,
        "ssh_client": os.environ.get("SSH_CLIENT", ""),
        "pid": os.getpid(),
    }


def container_identity(podman_bin):
    """The identity of the running container, before and after a restart."""
    try:
        res = subprocess.run(
            [podman_bin, "inspect", "t3code", "--format",
             '{{.Id}} {{.Image}} {{.State.StartedAt}} {{.State.Health.Status}} {{ index .Config.Labels "' + DEPLOYMENT_LABEL + '" }}'],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return {}
    if res.returncode != 0:
        return {}
    fields = res.stdout.strip().split()
    if not fields:
        return {}
    return {
        "id": fields[0],
        "image": fields[1] if len(fields) > 1 else "",
        "started_at": fields[2] if len(fields) > 2 else "",
        "health": fields[3] if len(fields) > 3 else "",
        "deployment": fields[4] if len(fields) > 4 else "",
    }


def record_restart(ledger_path, entry):
    """Append one restart to the ledger."""
    ledger = Path(ledger_path)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger.parent, 0o700)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    os.chmod(ledger, 0o600)


def journal_message(journal_bin, message):
    """Record the restart in the journal."""
    try:
        subprocess.run([journal_bin, "-t", "t3code-restart", "-p", "warning", message],
                       check=False, timeout=10)
    except Exception:
        pass


def force_restart(systemctl_bin, podman_bin, ledger_path, journal_bin, audit_log,
                  state_dir, image_archive, candidate_socket="/run/t3code-podman-candidate/podman.sock",
                  home_dir="/srv/apps/t3code/home",
                  volumes=(), candidate_acceptor=produce_candidate_receipt,
                  candidate_uid=62041,
                  candidate_runtime_dir="/var/lib/t3code-podman-candidate/acceptance",
                  provider_secrets_file=None, tooling_path=None,
                  expected_agent_revision=None,
                  candidate_home_target="/candidate-home"):
    """Restart T3 Code immediately after the exact image passes acceptance."""
    candidate_acceptor(
        state_dir, image_archive, podman_bin, candidate_socket, home_dir,
        volumes, candidate_uid,
        candidate_runtime_dir, provider_secrets_file,
        tooling_path,
        expected_agent_revision,
        candidate_home_target,
    )
    require_candidate(state_dir, image_archive, podman_bin, expected_agent_revision,
                      provider_secrets_file, tooling_path, candidate_home_target)
    pre = container_identity(podman_bin)
    print("Restarting podman-t3code.service after candidate acceptance...", flush=True)
    subprocess.run([systemctl_bin, "restart", "podman-t3code.service"], check=True)
    post = container_identity(podman_bin)
    if not live_inputs_match(podman_bin, tooling_path, provider_secrets_file,
                             candidate_home_target):
        raise RuntimeError("forced T3 pickup did not load the desired agent or secret projection")
    desired_file = Path(state_dir) / "desired"
    desired = desired_file.read_text().strip() if desired_file.is_file() else ""
    if expected_agent_revision or tooling_path or provider_secrets_file:
        if not desired:
            raise RuntimeError("forced T3 pickup is missing the desired deployment identity")
        write_live_inputs_receipt(
            state_dir, podman_bin, desired,
            expected_agent_revision, tooling_path, provider_secrets_file, candidate_home_target,
        )
    if desired:
        tmp_applied = Path(state_dir) / "applied.tmp"
        tmp_applied.write_text(desired)
        tmp_applied.replace(Path(state_dir) / "applied")
    desired_inputs_file = Path(state_dir) / "desired-inputs"
    if desired_inputs_file.is_file():
        tmp_inputs = Path(state_dir) / "applied-inputs.tmp"
        tmp_inputs.write_text(desired_inputs_file.read_text().strip() + "\n")
        tmp_inputs.replace(Path(state_dir) / "applied-inputs")
    entry = {"time": utcnow_iso(), "mode": "candidate-accepted", "actor": actor(),
             "pre": pre, "post": post}
    record_restart(ledger_path, entry)
    journal_message(journal_bin,
                    f"candidate-accepted T3 Code restart by {entry['actor']['user']}@{entry['actor']['host']}: "
                    f"before {pre.get('id', 'unknown')}, "
                    f"after {post.get('id', 'unknown')})")
    log(audit_log, "action=candidate-accepted-restart "
                   f"before={pre.get('id', '')} after={post.get('id', '')}")
    print("Restart issued.", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description="T3 Code deploy when idle")
    parser.add_argument("--json", action="store_true", help="print structured acceptance output")
    parser.add_argument("--state-dir", default="/var/lib/ghostship/t3code-deployment")
    parser.add_argument("--image-archive", help="the exact Nix-built image archive")
    parser.add_argument("--candidate-socket", default="/run/t3code-podman-candidate/podman.sock")
    parser.add_argument("--candidate-uid", type=int, default=62041)
    parser.add_argument("--candidate-runtime-dir", default="/var/lib/t3code-podman-candidate/acceptance")
    parser.add_argument("--provider-secrets-file")
    parser.add_argument("--tooling-path")
    parser.add_argument("--agent-revision")
    parser.add_argument("--expected-deployment-id", default="",
                        help="the target configuration's T3 deployment identity")
    parser.add_argument("--candidate-home-target", default="/candidate-home")
    parser.add_argument("--volume", action="append", default=[])
    parser.add_argument("--home-dir", default="/srv/apps/t3code/home")
    parser.add_argument("--podman-bin", default="podman")
    parser.add_argument("--systemctl-bin", default="systemctl")
    parser.add_argument("--audit-log", default="/srv/apps/t3code/home/.t3code-container/logs/restart-audit.log")
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    parser.add_argument("--safe-restart", action="store_true", help="Schedule a safe restart")
    parser.add_argument("--force", "--now", action="store_true", help="Force immediate restart")
    parser.add_argument("--verify-candidate", action="store_true",
                        help="verify and print the receipt for this build's exact T3 image")
    parser.add_argument("--accept-candidate", action="store_true",
                        help="test this build's exact T3 image without restarting production")
    parser.add_argument("--wait", action="store_true", help="Wait for scheduled restart to finish")
    parser.add_argument("--restart-ledger", default=RESTART_LEDGER,
                        help="The ledger of restarts that interrupted T3 Code")
    parser.add_argument("--journal-bin", default="systemd-cat",
                        help="The journal writer used for a forced restart")

    args = parser.parse_args()

    if args.verify_candidate or args.accept_candidate:
        try:
            if args.accept_candidate:
                produce_candidate_receipt(
                    args.state_dir, args.image_archive, args.podman_bin,
                    args.candidate_socket, args.home_dir, args.volume,
                    candidate_uid=args.candidate_uid,
                    candidate_runtime_dir=args.candidate_runtime_dir,
                    provider_secrets_file=args.provider_secrets_file,
                    tooling_path=args.tooling_path,
                    expected_agent_revision=args.agent_revision,
                    candidate_home_target=args.candidate_home_target,
                    deployment_id=args.expected_deployment_id,
                    force_test=True,
                )
            receipt = verify_candidate_receipt(
                args.state_dir, args.image_archive, args.expected_deployment_id,
                args.agent_revision, args.provider_secrets_file, args.tooling_path,
                args.candidate_home_target,
            )
        except (OSError, RuntimeError, tarfile.TarError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(receipt, sort_keys=True))
        return 0

    state_dir = Path(args.state_dir)
    pending_file = state_dir / "restart.pending"
    audit_path = Path(args.audit_log) if args.audit_log else None

    if args.safe_restart or args.force:
        if args.force:
            return force_restart(args.systemctl_bin, args.podman_bin,
                                 args.restart_ledger, args.journal_bin, audit_path,
                                 args.state_dir, args.image_archive, args.candidate_socket,
                                 args.home_dir, args.volume,
                                 candidate_uid=args.candidate_uid,
                                 candidate_runtime_dir=args.candidate_runtime_dir,
                                 provider_secrets_file=args.provider_secrets_file,
                                 tooling_path=args.tooling_path,
                                 expected_agent_revision=args.agent_revision,
                                 candidate_home_target=args.candidate_home_target)

        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = state_dir / "restart.pending.tmp"
        tmp.write_text(utcnow_iso() + "\n")
        tmp.replace(pending_file)

        print("Restart requested. Triggering t3code-deploy-when-idle.service...", flush=True)
        subprocess.run([args.systemctl_bin, "start", "t3code-deploy-when-idle.service"], check=False)

        if pending_file.exists():
            print("T3 Code is currently executing tasks or confirming sustained idle.", flush=True)
            print("The container restart has been safely queued and will execute as soon as all tasks finish.", flush=True)
        else:
            print("T3 Code was idle; restart completed successfully.", flush=True)

        if args.wait and pending_file.exists():
            print("Waiting for pending restart to complete...", flush=True)
            while pending_file.exists():
                time.sleep(5)
            print("Restart completed successfully.", flush=True)
        return 0

    sys.exit(
        run_deployment(
            state_dir=args.state_dir,
            home_dir=args.home_dir,
            podman_bin=args.podman_bin,
            systemctl_bin=args.systemctl_bin,
            audit_log=audit_path,
            health_timeout_seconds=args.health_timeout_seconds,
            image_archive=args.image_archive,
            candidate_socket=args.candidate_socket,
            candidate_uid=args.candidate_uid,
            candidate_runtime_dir=args.candidate_runtime_dir,
            provider_secrets_file=args.provider_secrets_file,
            tooling_path=args.tooling_path,
            expected_agent_revision=args.agent_revision,
            candidate_home_target=args.candidate_home_target,
            volumes=args.volume,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
