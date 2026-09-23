"""Stop an oversized T3 child process before it can exhaust the shared service cgroup."""

import json
import os
import signal
import sys
import time
from pathlib import Path

GIB = 1024**3
PROCESS_RSS_LIMIT = 12 * GIB
TERM_GRACE_SECONDS = 20
CGROUP_ROOT = Path("/sys/fs/cgroup")
PROC_ROOT = Path("/proc")
STATE_FILE = Path("/run/t3code-tool-update/process-memory-guard.json")
EXPECTED_CGROUP = "/system.slice/t3code-server.service"


def read_cgroup(proc_root, pid):
    try:
        lines = (proc_root / str(pid) / "cgroup").read_text().splitlines()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    for line in lines:
        try:
            hierarchy, controllers, path = line.split(":", 2)
        except ValueError:
            continue
        if hierarchy == "0" and not controllers:
            return path
    return None


def read_process(proc_root, pid):
    process = proc_root / str(pid)
    try:
        status = (process / "status").read_text().splitlines()
        rss_kib = next(
            int(line.split()[1]) for line in status if line.startswith("VmRSS:")
        )
        stat = (process / "stat").read_text().rsplit(")", 1)[1].split()
        start_time = int(stat[19])
    except (
        FileNotFoundError,
        PermissionError,
        ProcessLookupError,
        StopIteration,
        ValueError,
    ):
        return None
    return {"pid": pid, "rss": rss_kib * 1024, "start_time": start_time}


def is_in_cgroup(path, service_path):
    return path == service_path or path.startswith(service_path.rstrip("/") + "/")


def sample_processes(
    main_pid, service_path, cgroup_root=CGROUP_ROOT, proc_root=PROC_ROOT
):
    """Return RSS samples for live processes in the server cgroup subtree."""
    relative = Path(service_path.lstrip("/"))
    if ".." in relative.parts:
        return []
    service_cgroup = cgroup_root / relative
    if not service_cgroup.is_dir():
        return []

    pids = set()
    for pid_file in service_cgroup.rglob("cgroup.procs"):
        try:
            pids.update(int(value) for value in pid_file.read_text().split())
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError):
            continue

    samples = []
    for pid in pids:
        if pid == main_pid:
            continue
        if not is_in_cgroup(read_cgroup(proc_root, pid) or "", service_path):
            continue
        sample = read_process(proc_root, pid)
        if sample is not None:
            samples.append(sample)
    return samples


def select_offender(samples, main_pid, rss_limit=PROCESS_RSS_LIMIT):
    eligible = [
        sample
        for sample in samples
        if sample["pid"] != main_pid and sample["rss"] >= rss_limit
    ]
    return max(eligible, key=lambda sample: sample["rss"], default=None)


def evaluate(candidate, previous, now):
    """Choose one TERM, then one KILL after the grace period for the same PID."""
    if candidate is None:
        return {}, None
    same_process = (
        previous.get("pid") == candidate["pid"]
        and previous.get("start_time") == candidate["start_time"]
    )
    if not same_process:
        return {
            "pid": candidate["pid"],
            "start_time": candidate["start_time"],
            "term_sent_at": now,
            "signal": "TERM",
        }, signal.SIGTERM
    if previous.get("signal") == "KILL":
        return previous, None
    try:
        elapsed = now - float(previous["term_sent_at"])
    except (KeyError, TypeError, ValueError):
        elapsed = TERM_GRACE_SECONDS
    if elapsed >= TERM_GRACE_SECONDS:
        return {**previous, "signal": "KILL"}, signal.SIGKILL
    return previous, None


def signal_process(
    pid,
    start_time,
    main_pid,
    service_path,
    sig,
    cgroup_root=CGROUP_ROOT,
    proc_root=PROC_ROOT,
):
    """Signal only the same process identity while it remains in this cgroup."""
    if (
        pid == main_pid
        or not hasattr(os, "pidfd_open")
        or not hasattr(signal, "pidfd_send_signal")
    ):
        return False, "safe pidfd signaling is unavailable"
    try:
        pidfd = os.pidfd_open(pid, 0)
    except ProcessLookupError:
        return False, "process exited before signaling"
    except OSError as error:
        return False, f"could not open process handle ({error.strerror})"
    try:
        current = read_process(proc_root, pid)
        current_cgroup = read_cgroup(proc_root, pid)
        if current is None or current["start_time"] != start_time:
            return False, "process identity changed before signaling"
        if current["rss"] < PROCESS_RSS_LIMIT:
            return False, "process memory fell below the limit before signaling"
        if current_cgroup is None or not is_in_cgroup(current_cgroup, service_path):
            return False, "process left the server cgroup before signaling"
        signal.pidfd_send_signal(pidfd, sig)
        return True, ""
    except ProcessLookupError:
        return False, "process exited before signaling"
    except PermissionError:
        return False, "permission denied while signaling process"
    except OSError as error:
        return False, f"signal failed ({error.strerror})"
    finally:
        os.close(pidfd)


def load_state(path=STATE_FILE):
    try:
        state = json.loads(path.read_text())
        return state if isinstance(state, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return {}


def save_state(path, state):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(path)


def main():
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("usage: process-memory-guard.py MAIN_PID")
    main_pid = int(sys.argv[1])
    service_path = read_cgroup(PROC_ROOT, main_pid)
    if service_path != EXPECTED_CGROUP:
        raise SystemExit(
            "T3 server is not in its expected cgroup; refusing to signal processes"
        )

    relative = Path(service_path.lstrip("/"))
    if ".." in relative.parts:
        raise SystemExit("invalid T3 server cgroup path")
    samples = sample_processes(main_pid, service_path)
    previous = load_state()
    pending = next(
        (
            sample
            for sample in samples
            if sample["pid"] == previous.get("pid")
            and sample["start_time"] == previous.get("start_time")
            and sample["rss"] >= PROCESS_RSS_LIMIT
        ),
        None,
    )
    candidate = pending or select_offender(samples, main_pid)
    state, action = evaluate(candidate, previous, time.monotonic())
    if action is None:
        save_state(STATE_FILE, state)
        return

    sent, reason = signal_process(
        candidate["pid"],
        candidate["start_time"],
        main_pid,
        service_path,
        action,
    )
    if sent:
        save_state(STATE_FILE, state)
        name = signal.Signals(action).name
        print(
            f"oversized T3 child pid={candidate['pid']} "
            f"rss_gib={candidate['rss'] / GIB:.2f} signal={name}",
            file=sys.stderr,
        )
    else:
        if reason in {
            "process exited before signaling",
            "process identity changed before signaling",
            "process memory fell below the limit before signaling",
            "process left the server cgroup before signaling",
        }:
            save_state(STATE_FILE, {})
        print(
            f"T3 child guard skipped pid={candidate['pid']}: {reason}", file=sys.stderr
        )


if __name__ == "__main__":
    main()
