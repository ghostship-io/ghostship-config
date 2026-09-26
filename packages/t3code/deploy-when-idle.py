"""Deploy changed T3 Code container images and apply restarts safely when idle."""

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone


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


def is_live_idle(home_dir, state_db, probe_bin, podman_bin):
    """Check if T3 Code is definitely idle and safe to restart.

    1. Checks if internal tool-update lock is held.
    2. Runs activity probe against state.sqlite.
    3. Verifies container web endpoint responds.
    """
    tool_lock = home_dir / ".local/state/t3code-tool-update/tool-update.lock"
    if tool_lock.exists():
        try:
            with open(tool_lock, "r") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except (BlockingIOError, OSError):
                    return False
        except Exception:
            pass

    if state_db.is_file():
        env = dict(os.environ, T3CODE_STATE_DB=str(state_db))
        try:
            res = subprocess.run(
                [probe_bin],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            if res.returncode != 0:
                return False
        except Exception:
            return False

    try:
        res = subprocess.run(
            [
                podman_bin,
                "exec",
                "t3code",
                "curl",
                "-fsS",
                "--max-time",
                "5",
                "http://127.0.0.1:3773/",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if res.returncode != 0:
            return False
    except Exception:
        return False

    return True


def wait_healthy(podman_bin, timeout_seconds=120):
    start = time.monotonic()
    while time.monotonic() - start < timeout_seconds:
        try:
            inspect_proc = subprocess.run(
                [podman_bin, "inspect", "t3code", "--format", "{{.State.Health.Status}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            status = inspect_proc.stdout.strip()
            if status == "healthy":
                srv_proc = subprocess.run(
                    [podman_bin, "exec", "t3code", "systemctl", "is-active", "--quiet", "t3code-server.service"],
                    timeout=10,
                )
                if srv_proc.returncode == 0:
                    curl_proc = subprocess.run(
                        [podman_bin, "exec", "t3code", "curl", "-fsS", "--max-time", "5", "http://127.0.0.1:3773/"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                    if curl_proc.returncode == 0:
                        return True
        except Exception:
            pass
        time.sleep(5)
    return False


def run_deployment(
    state_dir,
    home_dir,
    probe_bin="t3code-activity-probe",
    podman_bin="podman",
    systemctl_bin="systemctl",
    audit_log=None,
    confirm_idle_seconds=30,
    health_timeout_seconds=120,
    idle_checker=None,
    healthy_waiter=None,
    sleep_fn=time.sleep,
):
    state_dir = Path(state_dir)
    home_dir = Path(home_dir)
    desired_file = state_dir / "desired"
    applied_file = state_dir / "applied"
    applying_file = state_dir / "applying"
    pending_file = state_dir / "restart.pending"
    state_db = home_dir / ".t3/userdata/state.sqlite"

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

        if not restart_pending and (not desired or desired == applied):
            return 0

        check_idle = idle_checker or (
            lambda: is_live_idle(home_dir, state_db, probe_bin, podman_bin)
        )
        wait_for_health = healthy_waiter or (
            lambda: wait_healthy(podman_bin, timeout_seconds=health_timeout_seconds)
        )

        is_active = False
        try:
            res = subprocess.run(
                [systemctl_bin, "is-active", "--quiet", "podman-t3code.service"],
                timeout=10,
            )
            is_active = (res.returncode == 0)
        except Exception:
            pass

        if is_active:
            if not check_idle():
                log(audit_log, f"action=defer desired={desired} restart_pending={restart_pending} reason=active-or-unknown")
                return 0

            log(audit_log, f"action=idle-confirmation desired={desired} restart_pending={restart_pending} wait_seconds={confirm_idle_seconds}")
            sleep_fn(confirm_idle_seconds)

            if not check_idle():
                log(audit_log, f"action=defer desired={desired} restart_pending={restart_pending} reason=activity-resumed")
                return 0

        if desired:
            tmp_applying = state_dir / "applying.tmp"
            tmp_applying.write_text(desired)
            tmp_applying.replace(applying_file)

        log(audit_log, f"action=restart-container desired={desired} restart_pending={restart_pending}")
        subprocess.run([systemctl_bin, "restart", "podman-t3code.service"], check=True, timeout=300)

        if not wait_for_health():
            log(audit_log, f"action=deployment-failed desired={desired}")
            return 1

        if desired:
            tmp_applied = state_dir / "applied.tmp"
            tmp_applied.write_text(desired)
            tmp_applied.replace(applied_file)

        if applying_file.exists():
            applying_file.unlink()
        if pending_file.exists():
            pending_file.unlink()

        log(audit_log, f"action=deployment-complete desired={desired}")
        return 0
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="T3 Code deploy when idle")
    parser.add_argument("--state-dir", default="/var/lib/ghostship/t3code-deployment")
    parser.add_argument("--home-dir", default="/srv/apps/t3code/home")
    parser.add_argument("--probe-bin", default="t3code-activity-probe")
    parser.add_argument("--podman-bin", default="podman")
    parser.add_argument("--systemctl-bin", default="systemctl")
    parser.add_argument("--audit-log", default="/srv/apps/t3code/home/.t3code-container/logs/restart-audit.log")
    parser.add_argument("--confirm-idle-seconds", type=int, default=30)
    parser.add_argument("--health-timeout-seconds", type=int, default=120)
    parser.add_argument("--safe-restart", action="store_true", help="Schedule a safe restart")
    parser.add_argument("--force", "--now", action="store_true", help="Force immediate restart")
    parser.add_argument("--wait", action="store_true", help="Wait for scheduled restart to finish")

    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    pending_file = state_dir / "restart.pending"

    if args.safe_restart:
        if args.force:
            print("Forcing immediate restart of podman-t3code.service...", flush=True)
            subprocess.run([args.systemctl_bin, "restart", "podman-t3code.service"], check=True)
            print("Restart issued.", flush=True)
            return 0

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

    audit_path = Path(args.audit_log) if args.audit_log else None
    sys.exit(
        run_deployment(
            state_dir=args.state_dir,
            home_dir=args.home_dir,
            probe_bin=args.probe_bin,
            podman_bin=args.podman_bin,
            systemctl_bin=args.systemctl_bin,
            audit_log=audit_path,
            confirm_idle_seconds=args.confirm_idle_seconds,
            health_timeout_seconds=args.health_timeout_seconds,
        )
    )


if __name__ == "__main__":
    main()
