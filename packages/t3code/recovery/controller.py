"""Independent host recovery controller; the advisor supplies data, never commands.

Nix supplies all configuration, the unprivileged static advisor unit and its
480-second lifetime limit. Only this root process can issue a fixed repair.
Continuity is deliberately memory-only; attempts and the rolling budget are not.
"""

import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import time

ACTIONS = {"none", "start_server", "restart_proxy", "start_container", "restart_container"}
TOOL_LOCK = Path(".local/state/t3code-tool-update/tool-update.lock")
RESTART_LEDGER = Path("/var/lib/t3code-restarts/ledger.jsonl")
PROC_ROOT = Path("/proc")
CGROUP_ROOT = Path("/sys/fs/cgroup")
SAMPLE_SECONDS = 30
MAX_GAP = 45
DOWN_SECONDS = 300
REARM_SECONDS = 600
BUDGET_SECONDS = 86400
MAX_LAUNCHES = 3
ADVISOR_SECONDS = 480
DATA_LIMIT = 65536
PROPOSAL_LIMIT = 16384
CONFIG_FIELDS = {"state_dir", "runtime_dir", "home_dir", "deployment_state_dir", "podman_bin",
                 "systemctl_bin", "nsenter_bin", "curl_bin", "probe_bin", "advisor_unit", "owner_approval"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def decode_json(value):
    return json.loads(value, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def validate_proposal(value):
    if not isinstance(value, dict) or set(value) != {"action", "diagnosis", "confidence", "evidence"}:
        return False
    return (isinstance(value["action"], str) and value["action"] in ACTIONS
            and isinstance(value["diagnosis"], str) and len(value["diagnosis"]) <= 2000
            and isinstance(value["confidence"], str) and value["confidence"] in {"low", "medium", "high"}
            and isinstance(value["evidence"], list) and len(value["evidence"]) <= 10
            and all(isinstance(item, str) and len(item) <= 200 for item in value["evidence"]))


def read_proposal(path):
    """Never follow an advisor-created link, block on a FIFO, or read past the cap."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > PROPOSAL_LIMIT:
                return None
            data = handle.read(PROPOSAL_LIMIT + 1)
        if len(data) > PROPOSAL_LIMIT:
            return None
        result = decode_json(data)
        return result if validate_proposal(result) else None
    except (OSError, ValueError, RecursionError):
        return None


def identity(observation):
    container = observation.get("container") or {}
    values = container.get("id"), container.get("started_at")
    return values if all(isinstance(value, str) and value for value in values) else None


def health(observation):
    if identity(observation) is None or observation.get("host_state") not in {"active", "inactive", "failed"}:
        return "unknown"
    if "metrics" in observation and observation["metrics"].get("status") != "known":
        return "unknown"
    container = observation["container"]
    if container.get("running") is False:
        return "down" if observation["host_state"] in {"inactive", "failed"} else "unknown"
    if container.get("running") is not True or observation["host_state"] != "active":
        return "unknown"
    if observation.get("management") == "transitioning":
        return "unknown"
    native, proxy = observation.get("native"), observation.get("proxy")
    app = observation.get("app")
    if type(app) is not bool:
        return "unknown"
    if native is True and proxy is True and app is True:
        return "up"
    if type(native) is not bool or type(proxy) is not bool:
        return "unknown"
    # A failed HTTP request is not evidence that server/provider tasks are gone.
    if observation.get("server_state") not in {"empty", "populated"}:
        return "unknown"
    if observation.get("management") not in {"available", "unavailable"}:
        return "unknown"
    return "down"


def eligible_actions(observation):
    if health(observation) != "down":
        return set()
    if observation["container"]["running"] is False:
        return {"start_container"}
    # A live static server with a failed authenticated DB lookup is advice-only.
    if observation["native"] is True and observation.get("app") is not True:
        return set()
    if observation["native"] is True and observation["proxy"] is False:
        return {"restart_proxy"} if observation.get("management") == "available" else set()
    if observation.get("app") is True or observation.get("server_state") != "empty":
        return set()
    if observation["native"] is not False or observation["proxy"] is not False:
        return set()
    if observation.get("management") == "available":
        return {"start_server"}
    if observation.get("management") == "unavailable":
        return {"restart_container"}
    return set()


def atomic_json(path, value):
    """Persist before an external effect, including across power loss."""
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def properties(output):
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def bounded_text(path, limit=4096):
    with path.open("r", encoding="ascii") as handle:
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError("metric size limit exceeded")
    return value


def counter(value):
    value = value.strip()
    if not value.isascii() or not value.isdecimal() or len(value) > 20:
        raise ValueError("invalid metric")
    number = int(value)
    if number > 2**64 - 1:
        raise ValueError("metric out of range")
    return number


class Host:
    def __init__(self, config):
        self.config = config

    def notify(self, message):
        # StandardError=journal in the host service; no extra process needed.
        print("t3code-recovery: " + message[:2000], file=sys.stderr, flush=True)

    def command(self, argv, timeout=5, input_data=None):
        """Fixed argv only, bounded time and combined stdout/stderr, no shell."""
        output = bytearray()
        try:
            process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL, close_fds=True)
        except OSError:
            return None, ""
        deadline = time.monotonic() + timeout
        try:
            if input_data is not None:
                # Bounded below PIPE_BUF; credentials never enter argv or logs.
                if len(input_data) > 4096:
                    return None, ""
                process.stdin.write(input_data)
                process.stdin.close()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None, ""
                    if not selector.select(remaining):
                        return None, ""
                    data = os.read(process.stdout.fileno(), 4096)
                    if not data:
                        selector.unregister(process.stdout)
                        continue
                    if len(output) + len(data) > DATA_LIMIT:
                        return None, ""
                    output.extend(data)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, ""
            return process.wait(timeout=remaining), output.decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            return None, ""
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass

    def inspect(self):
        rc, output = self.command([self.config["podman_bin"], "inspect", "t3code"])
        if rc != 0:
            return None
        try:
            records = decode_json(output)
            if not isinstance(records, list) or len(records) != 1:
                return None
            record = records[0]
            state = record["State"]
            pid = state["Pid"]
            if type(pid) is not int or type(state["Running"]) is not bool or state.get("Paused", False):
                return None
            if (state["Running"] and pid <= 0) or (not state["Running"] and pid != 0):
                return None
            value = dict(id=record["Id"], started_at=state["StartedAt"], running=state["Running"], pid=pid)
            return value if identity({"container": value}) else None
        except (KeyError, TypeError, ValueError, RecursionError):
            return None

    def container_cgroup(self, pid):
        """Resolve PID 1's host hierarchy, including systemd's init.scope."""
        try:
            lines = bounded_text(PROC_ROOT / str(pid) / "cgroup").splitlines()
            unified = [line[3:] for line in lines if line.startswith("0::")]
            if len(unified) != 1 or not unified[0].startswith("/") or ".." in Path(unified[0]).parts:
                return None
            root = CGROUP_ROOT / unified[0].lstrip("/")
            if root == CGROUP_ROOT or root.resolve() != root or not root.is_dir():
                return None
            events = properties(bounded_text(root / "cgroup.events").replace(" ", "="))
            if events.get("populated") != "1":
                return None
            if root.name == "init.scope":
                root = root.parent
                events = properties(bounded_text(root / "cgroup.events").replace(" ", "="))
                if events.get("populated") != "1":
                    return None
            return root
        except (OSError, ValueError):
            return None

    def server_cgroup(self, pid):
        """populated covers descendants. Absence requires a verified parent.

        Never inspect conmon's cgroup or treat an unreadable hierarchy as empty.
        """
        try:
            root = self.container_cgroup(pid)
            if root is None:
                return "unknown"
            parent = root / "system.slice"
            if parent.resolve() != parent or not parent.is_dir():
                return "unknown"
            service = parent / "t3code-server.service"
            if not service.exists():
                # stat, rather than exists(), must report permissions/I/O errors.
                try:
                    service.stat()
                except FileNotFoundError:
                    return "empty"
                return "unknown"
            if service.resolve() != service:
                return "unknown"
            contents = bounded_text(service / "cgroup.events")
            events = properties(contents.replace(" ", "="))
            return {"0": "empty", "1": "populated"}.get(events.get("populated"), "unknown")
        except (OSError, ValueError):
            return "unknown"

    def cgroup_metrics(self, root, host_root=False):
        """Selected counters only; no process names, environment or log text.

        At the hierarchy root some limit/controller files do not exist by
        kernel design. Those are null, as are explicit unlimited ('max') values.
        Missing files in an actual container/service cgroup remain unknown.
        """
        result = {"status": "known"}
        files = ("pids.current", "pids.max", "pids.events", "memory.current", "memory.high", "memory.max", "memory.events")
        if not root.is_dir() or root.resolve() != root:
            return {"status": "unknown"}
        for name in files:
            key = name.replace(".", "_")
            result[key] = None
            try:
                value = bounded_text(root / name)
                if name.endswith(".events"):
                    selected = {"max"} if name == "pids.events" else {"low", "high", "max", "oom", "oom_kill", "oom_group_kill"}
                    events = {}
                    seen = set()
                    for line in value.splitlines():
                        field, number = line.split()
                        if field in seen:
                            raise ValueError("duplicate metric")
                        seen.add(field)
                        parsed = counter(number)
                        if field in selected:
                            events[field] = parsed
                    required = {"max"} if name == "pids.events" else {"low", "high", "max", "oom", "oom_kill"}
                    if not required <= events.keys():
                        raise ValueError("missing event counters")
                    result[key] = events
                else:
                    result[key] = None if value.strip() == "max" and name in {"pids.max", "memory.high", "memory.max"} else counter(value)
            except FileNotFoundError:
                if not host_root:
                    result["status"] = "unknown"
            except (OSError, ValueError):
                result["status"] = "unknown"
        if result["pids_current"] is not None and result["pids_max"] is not None:
            result["pids_headroom"] = max(0, result["pids_max"] - result["pids_current"])
        return result

    def host_metrics(self):
        result = {"status": "known", "cgroup": self.cgroup_metrics(CGROUP_ROOT, host_root=True)}
        try:
            for name, key in (("pid_max", "pid_max"), ("threads-max", "threads_max")):
                result[key] = counter(bounded_text(PROC_ROOT / "sys/kernel" / name))
            fields = bounded_text(PROC_ROOT / "loadavg").split()
            runnable, total = fields[3].split("/")
            result.update(runnable_threads=counter(runnable), threads=counter(total))
            memory = {}
            for line in bounded_text(PROC_ROOT / "meminfo", 16384).splitlines():
                key, value = line.split(":", 1)
                if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                    amount, unit = value.split()
                    if unit != "kB" or key in memory:
                        raise ValueError("invalid memory metric")
                    memory[key] = counter(amount) * 1024
            for source, key in (("MemTotal", "memory_total_bytes"), ("MemAvailable", "memory_available_bytes"),
                                ("SwapTotal", "swap_total_bytes"), ("SwapFree", "swap_free_bytes")):
                result[key] = memory[source]
        except (OSError, ValueError, IndexError, KeyError):
            result["status"] = "unknown"
        if result["cgroup"]["status"] != "known":
            result["status"] = "unknown"
        return result

    def metrics(self, observation):
        host = self.host_metrics()
        result = dict(status=host["status"], host=host, container={"status": "absent"}, server={"status": "absent"})
        container = observation.get("container") or {}
        if container.get("running") is True:
            root = self.container_cgroup(container["pid"])
            if root is None:
                result.update(status="unknown", container={"status": "unknown"}, server={"status": "unknown"})
                return result
            result["container"] = self.cgroup_metrics(root)
            server = root / "system.slice/t3code-server.service"
            if server.is_dir():
                result["server"] = self.cgroup_metrics(server)
            elif self.server_cgroup(container["pid"]) != "empty":
                result["server"] = {"status": "unknown"}
            if any(result[key]["status"] == "unknown" for key in ("container", "server")):
                result["status"] = "unknown"
        elif container.get("running") is not False:
            result["status"] = "unknown"
        return result

    def http(self, pid, port):
        results = []
        for endpoint in ("/", "/.well-known/t3/environment"):
            argv = [self.config["nsenter_bin"], "--target", str(pid), "--net", "--",
                    self.config["curl_bin"], "--fail", "--silent", "--show-error", "--noproxy", "*",
                    "--output", "/dev/null", "--max-time", "5", f"http://127.0.0.1:{port}{endpoint}"]
            rc, _ = self.command(argv, timeout=6)
            # nsenter/exec failures, missing curl, signals and command timeouts
            # cannot establish a failed HTTP endpoint.
            results.append(True if rc == 0 else False if rc in {7, 22, 28, 52, 56} else None)
        if None in results:
            return None
        return all(results)

    def authenticated_app(self, pid):
        """Native auth lookup exercises the app's session database, not static HTML.

        Reuse the proxy's private session without issuing/refreshing credentials.
        Rejected auth and invalid responses are unknown, never repair authority.
        """
        session = Path(self.config["home_dir"]) / ".t3code-container/access/session.json"
        try:
            fd = os.open(session, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > DATA_LIMIT:
                    return None
                value = decode_json(handle.read(DATA_LIMIT + 1))
            token = value["token"]
            if (not isinstance(token, str) or not token or len(token) > 4000
                    or any(ord(char) < 33 or ord(char) > 126 for char in token)):
                return None
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            return None
        argv = [self.config["nsenter_bin"], "--target", str(pid), "--net", "--",
                self.config["curl_bin"], "--silent", "--show-error", "--noproxy", "*",
                "--header", "@-", "--max-time", "5", "--write-out", "\n%{http_code}",
                "http://127.0.0.1:3774/api/auth/session"]
        rc, output = self.command(argv, timeout=6,
                                  input_data=f"Authorization: Bearer {token}\n".encode("ascii"))
        if rc in {7, 28, 52, 56}:
            return False
        if rc != 0:
            return None
        body, _, status = output.rpartition("\n")
        if status in {"500", "502", "503", "504"}:
            return False
        if status != "200":
            return None
        try:
            result = decode_json(body)
            return True if isinstance(result, dict) and result.get("authenticated") is True else None
        except (ValueError, RecursionError):
            return None

    def management(self):
        rc, output = self.command([self.config["podman_bin"], "exec", "t3code", "systemctl", "show",
                                   "t3code-server.service", "--property=LoadState,ActiveState"])
        info = properties(output)
        if rc == 0 and info.get("LoadState") == "loaded":
            if info.get("ActiveState") in {"activating", "deactivating", "reloading", "refreshing"}:
                return "transitioning"
            return "available" if info.get("ActiveState") in {"active", "inactive", "failed"} else "unknown"
        # Runtime exec refusal or a positively identified failed system bus.
        if rc in {125, 126, 127} or (rc == 1 and "Failed to connect to bus:" in output):
            return "unavailable"
        return "unknown"

    def probe(self):
        container = self.inspect()
        rc, output = self.command([self.config["systemctl_bin"], "is-active", "podman-t3code.service"])
        host_state = output.strip() if rc in {0, 3} else "unknown"
        observed = dict(container=container, host_state=host_state, server_state="unknown",
                        management="unknown", native=None, proxy=None, app=None)
        if container and container["running"] and host_state == "active":
            observed["native"] = self.http(container["pid"], 3774)
            observed["proxy"] = self.http(container["pid"], 3773)
            observed["app"] = self.authenticated_app(container["pid"])
            observed["failure"] = ("app-db-stalled" if observed["native"] is True and observed["app"] is False
                                   else "proxy-down" if observed["app"] is True and observed["proxy"] is False
                                   else None)
            observed["management"] = self.management()
            observed["server_state"] = self.server_cgroup(container["pid"])
        observed["metrics"] = self.metrics(observed)
        # Close PID reuse/container replacement races during all observations.
        if container and self.inspect() != container:
            observed["container"] = None
        return observed

    def maintenance_held(self, observation):
        paths = [Path(self.config["state_dir"]) / "hold", Path(self.config["runtime_dir"]) / "hold",
                 Path(self.config["runtime_dir"]) / "maintenance",
                 Path(self.config["deployment_state_dir"]) / "restart.pending",
                 Path(self.config["home_dir"]) / ".local/state/t3code-tool-update/hold",
                 Path(self.config["home_dir"]) / ".local/state/t3code-tool-update/restart.pending",
                 Path(self.config["home_dir"]) / ".local/share/t3code-tools/t3/activation.pending"]
        container = observation.get("container") or {}
        if container.get("running") is True:
            root = PROC_ROOT / str(container["pid"]) / "root"
            # A missing namespace root is ambiguous, not an absence of holds.
            if not root.is_dir():
                return True
            paths.extend(root / "run/t3code-tool-update" / name for name in ("hold", "maintenance", "restart.pending"))
        try:
            for path in paths:
                try:
                    path.lstat()
                    return True
                except FileNotFoundError:
                    pass
            return False
        except OSError:
            return True

    @contextmanager
    def gates(self, observation):
        descriptors = []
        allowed = False
        try:
            if not self.maintenance_held(observation):
                deployment = Path(self.config["deployment_state_dir"])
                deployment.mkdir(parents=True, exist_ok=True)
                tool = Path(self.config["home_dir"]) / TOOL_LOCK
                tool.parent.mkdir(parents=True, exist_ok=True)
                for lock in (deployment / "deploy.lock", tool):
                    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    descriptors.append(fd)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                allowed = not self.maintenance_held(observation)
        except OSError:
            allowed = False
        try:
            yield allowed
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def advise(self, diagnostics, keep_running):
        data = json.dumps(diagnostics).encode("utf-8")
        if len(data) > DATA_LIMIT:
            self.notify("diagnostics exceed size limit")
            return None
        unit = self.config["advisor_unit"]
        rc, output = self.command([self.config["systemctl_bin"], "show", unit,
                                   "--property=ActiveState,SubState,Result"])
        if rc != 0 or properties(output).get("ActiveState") not in {"inactive", "failed"}:
            self.notify("advisor was already active or its state was unknown")
            return None
        runtime = Path(self.config["runtime_dir"])
        runtime.mkdir(parents=True, exist_ok=True)
        exchange = runtime / "advisor"
        exchange.mkdir(mode=0o700, exist_ok=True)
        if exchange.is_symlink() or not exchange.is_dir():
            return None
        os.chown(exchange, 3000, 3000)
        os.chmod(exchange, 0o700)
        output_path = exchange / "proposal.json"
        output_path.unlink(missing_ok=True)
        # systemd's single-file BindPaths source must exist before the unit
        # starts. The advisor overwrites this inode; it must not replace it.
        fd = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.fchown(fd, 3000, 3000)
        os.close(fd)
        # Stage in a root-owned parent; the advisor cannot substitute a symlink
        # while root is writing diagnostics. Rename replaces an existing link.
        temporary = runtime / "diagnostics.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(temporary, 0o444)
        temporary.replace(exchange / "diagnostics.json")
        deadline = time.monotonic() + ADVISOR_SECONDS
        started = False
        finished = False
        try:
            started = True  # Even a timed-out start may have reached systemd.
            rc, _ = self.command([self.config["systemctl_bin"], "start", "--no-block", unit])
            if rc != 0:
                return None
            while time.monotonic() < deadline:
                if not keep_running():
                    self.notify("advisor cancelled: health, identity, evidence or gates changed")
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                rc, output = self.command([self.config["systemctl_bin"], "show", unit,
                                           "--property=ActiveState,SubState,Result"], timeout=min(5, remaining))
                info = properties(output)
                if rc != 0:
                    return None
                if info.get("ActiveState") == "inactive" and info.get("Result") == "success":
                    finished = True
                    return read_proposal(output_path)
                if info.get("ActiveState") not in {"active", "activating"}:
                    return None
                time.sleep(min(5, max(0, deadline - time.monotonic())))
            self.notify("advisor timed out")
            return None
        finally:
            if started and not finished:
                self.command([self.config["systemctl_bin"], "stop", unit])

    def ledger(self, entry):
        # Same host ledger and pre/post/reference format as deploy-when-idle.py.
        path = Path(RESTART_LEDGER)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a") as handle:
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def mutate(self, action, observation):
        # The caller holds deploy.lock and the tool lock and has re-probed.
        if not self.config["owner_approval"].strip() or action not in eligible_actions(observation):
            return False
        commands = {
            "start_server": [self.config["podman_bin"], "exec", "t3code", "systemctl", "start", "t3code-server.service"],
            "restart_proxy": [self.config["podman_bin"], "exec", "t3code", "systemctl", "restart", "t3code-access-proxy.service"],
            "start_container": [self.config["systemctl_bin"], "start", "podman-t3code.service"],
            "restart_container": [self.config["systemctl_bin"], "restart", "podman-t3code.service"],
        }
        if action not in commands:
            return False
        if self.inspect() != observation["container"]:
            return False
        if action in {"start_server", "restart_proxy"} and self.management() != "available":
            return False
        if action == "restart_container" and self.management() != "unavailable":
            return False
        if action in {"start_server", "restart_container"} and self.server_cgroup(observation["container"]["pid"]) != "empty":
            return False
        entry = None
        if action in {"start_container", "restart_container"}:
            entry = dict(time=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), mode="auto-recovery",
                         reference=self.config["owner_approval"], owner_approval=self.config["owner_approval"],
                         action=action, pre=observation["container"], post={}, phase="before")
            self.ledger(entry)  # A ledger failure prevents the mutation.
        rc, _ = self.command(commands[action], timeout=300)
        if entry:
            entry.update(phase="after", post=self.inspect() or {}, success=rc == 0)
            self.ledger(entry)
        if rc != 0:
            self.notify("repair failed: " + action)
        return rc == 0

    def verify_health(self):
        """Observe actual HTTP health after a mutation; never retry a repair."""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if health(self.probe()) == "up":
                return True
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(5, remaining))
        return False


class Controller:
    def __init__(self, config, host=None, clock=time.monotonic, wall=time.time, sleep=time.sleep):
        self.config, self.clock, self.wall, self.sleep = config, clock, wall, sleep
        self.host = host or Host(config)
        self.state_dir = Path(config["state_dir"])
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.state_path = self.state_dir / "state.json"
        self.state = dict(version=1, attempted=False, launches=[], runs=[])
        try:
            raw = self.state_path.read_bytes()
        except FileNotFoundError:
            raw = None
        if raw is not None:
            try:
                saved = decode_json(raw)
                if (len(raw) > 131072 or not isinstance(saved, dict) or set(saved) != set(self.state)
                        or saved["version"] != 1 or type(saved["attempted"]) is not bool
                        or not isinstance(saved["launches"], list) or len(saved["launches"]) > MAX_LAUNCHES
                        or any(type(t) not in {int, float} or not math.isfinite(t) or t < 0 for t in saved["launches"])
                        or not isinstance(saved["runs"], list) or len(saved["runs"]) > 20):
                    raise ValueError("invalid state")
                self.state = saved
            except (ValueError, TypeError, RecursionError) as error:
                raise ValueError("invalid recovery state; refusing to reset budget") from error
        self.previous = self.down_since = self.healthy_since = self.signature = None
        self.last_identity = None

    def save(self):
        atomic_json(self.state_path, self.state)

    def audit(self, entry, replace=False):
        # Keep diagnosis and command output out of the journal. Bounded root
        # metadata is sufficient to reconstruct every attempted decision.
        bounded = {key: value[:2000] if isinstance(value, str) else value for key, value in entry.items()}
        if len(json.dumps(bounded)) > 3000:
            bounded = {"outcome": "audit-entry-too-large"}
        previous = self.state["runs"][:-1] if replace and self.state["runs"] else self.state["runs"]
        self.state["runs"] = (previous + [bounded])[-20:]
        self.save()

    def reset_down(self):
        self.down_since = self.signature = None

    def observe(self, observed, now):
        state = health(observed)
        current_identity = identity(observed)
        if self.last_identity is not None and current_identity != self.last_identity:
            self.reset_down()
            self.healthy_since = None
        self.last_identity = current_identity
        if self.previous is not None and not 0 <= now - self.previous <= MAX_GAP:
            self.reset_down()
            self.healthy_since = None
        self.previous = now
        if state == "up":
            self.reset_down()
            if self.healthy_since is None:
                self.healthy_since = now
            if now - self.healthy_since >= REARM_SECONDS and self.state["attempted"]:
                self.state["attempted"] = False
                self.save()
        else:
            self.healthy_since = None
            if state != "down":
                self.reset_down()
        return state

    def tick(self):
        now = self.clock()
        observed = self.host.probe()
        status = self.observe(observed, now)
        if status != "down":
            return
        with self.host.gates(observed) as allowed:
            if not allowed or not self.config["owner_approval"].strip():
                self.reset_down()
                return
        signature = (identity(observed), frozenset(eligible_actions(observed)))
        if self.signature != signature or self.down_since is None:
            self.signature, self.down_since = signature, now
        if now - self.down_since < DOWN_SECONDS or self.state["attempted"]:
            return
        wall = self.wall()
        self.state["launches"] = [timestamp for timestamp in self.state["launches"] if wall - timestamp < BUDGET_SECONDS]
        if len(self.state["launches"]) >= MAX_LAUNCHES:
            return
        self.state["attempted"] = True
        self.state["launches"].append(wall)
        self.save()  # Do not launch even the unprivileged advisor before fsync.
        self.audit(dict(time=wall, action="none", outcome="advisor-attempted"))
        outcome = "advisor-failed"
        action = "none"
        try:
            def keep_running():
                fresh = self.host.probe()
                moment = self.clock()
                state = self.observe(fresh, moment)
                with self.host.gates(fresh) as allowed:
                    valid = (allowed and state == "down" and self.signature == signature
                             and identity(fresh) == signature[0]
                             and frozenset(eligible_actions(fresh)) == signature[1])
                if not valid:
                    self.reset_down()
                return valid

            answer = self.host.advise(dict(observation=observed, eligible_actions=sorted(signature[1]),
                                          down_seconds=now - self.down_since), keep_running)
            if not validate_proposal(answer):
                outcome = "invalid-or-missing-proposal"
                return
            action = answer["action"]
            if action == "none":
                outcome = "advice-only"
                return
            if action not in signature[1]:
                outcome = "ineligible-proposal"
                return
            with self.host.gates(observed) as allowed:
                if not allowed:
                    outcome = "gated-after-advice"
                    return
                fresh = self.host.probe()
                # No model assertion can replace a fresh independent check.
                if (self.signature != signature or identity(fresh) != signature[0]
                        or health(fresh) != "down" or action not in eligible_actions(fresh)
                        or self.host.maintenance_held(fresh)):
                    outcome = "changed-after-advice"
                    return
                # Persist the single mutation decision before issuing it too.
                self.audit(dict(time=wall, action=action, outcome="mutation-attempted"), replace=True)
                if self.host.mutate(action, fresh):
                    outcome = "repaired" if self.host.verify_health() else "repair-unhealthy"
                else:
                    outcome = "repair-failed"
        except Exception:
            # No retry after an advisor, I/O or mutation error: attempted is
            # already durable. Error text may contain private command output.
            outcome = "controller-run-failed"
        finally:
            self.audit(dict(time=wall, action=action, outcome=outcome), replace=True)
            self.host.notify(outcome + ": " + action)


def load_config(path):
    config = decode_json(Path(path).read_bytes())
    if (not isinstance(config, dict) or set(config) != CONFIG_FIELDS
            or any(not isinstance(value, str) for value in config.values())
            or any(not Path(config[key]).is_absolute() for key in ("state_dir", "runtime_dir", "home_dir", "deployment_state_dir"))
            or not config["advisor_unit"].endswith(".service") or config["advisor_unit"].startswith("-")):
        raise ValueError("invalid controller configuration")
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="root-owned JSON configuration")
    parser.add_argument("--once", action="store_true", help="one observation, without retaining timing across processes")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("the host controller must run as root")
    config = load_config(args.config)
    state_dir = Path(config["state_dir"])
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(state_dir / "controller.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        controller = Controller(config)
        if args.once:
            controller.tick()
        else:
            while True:
                started = time.monotonic()
                controller.tick()
                time.sleep(max(0, SAMPLE_SECONDS - (time.monotonic() - started)))
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
