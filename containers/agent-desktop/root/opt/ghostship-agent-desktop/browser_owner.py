#!/usr/bin/env python3
"""Owns the Ghostship agent desktop Camoufox browsers.

Hybrid model:

  agent, personal   persistent headed browser instances with their own saved
                    authentication state, bound over Playwright WebSocket for
                    concurrent use
  temp-<id>         on demand isolated browser instances for parallel or
                    untrusted work; they can optionally start from a copy of a
                    persistent profile's storage state

Each instance runs in its own thread with its own Playwright server. Clients
connect with the native Playwright API (`firefox.connect(endpoint)`) and create
their own tabs in the instance's single shared context. Persistent instances
save storage state periodically and on shutdown; a janitor closes unpinned
tabs that have been idle for TAB_TTL seconds and shuts down idle temporary
instances.

A small loopback JSON API (default 127.0.0.1:7999) manages the instances; the
authenticated desktop API proxy is the only surface exposed to agents.
"""

import json
import os
import queue
import re
import secrets
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from camoufox.sync_api import Camoufox, NewContext

DATA_DIR = os.environ.get("AGENT_DESKTOP_DATA", "/config/agent-desktop")
BROWSER_DIR = os.path.join(DATA_DIR, "browsers")
PROFILE_DIR = os.path.join(DATA_DIR, "profiles")
MANAGER_BIND = os.environ.get("AGENT_DESKTOP_MANAGER_BIND", "127.0.0.1")
MANAGER_PORT = int(os.environ.get("AGENT_DESKTOP_MANAGER_PORT", "7999"))
PERSISTENT = {
    "agent": 7901,
    "personal": 7902,
}
EPHEMERAL_PORT_BASE = 7910
STATE_SAVE_INTERVAL = 120
TAB_TTL = int(os.environ.get("AGENT_DESKTOP_TAB_TTL", str(24 * 3600)))
TEMP_IDLE_TTL = int(os.environ.get("AGENT_DESKTOP_TEMP_IDLE_TTL", str(4 * 3600)))
PIN_PREFIX = "ghostship:pin"


def log(message):
    print(f"[browser-owner] {message}", file=sys.stderr, flush=True)


def atomic_write_json(path, payload):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


class Instance(threading.Thread):
    def __init__(self, instance_id, port, state_path=None, seed_state=None, ephemeral=False):
        super().__init__(daemon=True)
        self.instance_id = instance_id
        self.port = port
        self.state_path = state_path
        self.seed_state = seed_state
        self.ephemeral = ephemeral
        self.endpoint = None
        self.pages = {}
        self.started = time.time()
        self.stop_requested = threading.Event()
        self.commands = queue.Queue()
        self.error = None
        self.exit_code = None

    @property
    def endpoint_file(self):
        return os.path.join(BROWSER_DIR, f"{self.instance_id}.json")

    def status(self):
        return {
            "id": self.instance_id,
            "kind": "ephemeral" if self.ephemeral else "persistent",
            "port": self.port,
            "endpoint": self.endpoint,
            "pages": len(self.pages),
            "started": self.started,
            "error": self.error,
        }

    def request_stop(self):
        self.stop_requested.set()

    def run(self):
        options = dict(
            headless=False,
            humanize=True,
            os="linux",
            locale="en-US",
            window=(1280, 800),
        )
        log(f"launching instance {self.instance_id} on port {self.port}")
        try:
            with Camoufox(**options) as browser:
                context_kwargs = {}
                if self.state_path and os.path.exists(self.state_path):
                    context_kwargs["storage_state"] = self.state_path
                if self.seed_state and os.path.exists(self.seed_state):
                    context_kwargs["storage_state"] = self.seed_state
                context = NewContext(browser, **context_kwargs)
                keep = context.new_page()
                keep.goto("about:blank")
                self.pages[keep] = {"keepalive": True, "idle_since": time.time()}
                keep.on("framenavigated", lambda page: self.touch(page))
                context.on("page", self.on_page)
                server_info = browser.bind(
                    f"agent-desktop-{self.instance_id}", host="127.0.0.1", port=self.port
                )
                self.endpoint = server_info["endpoint"]
                atomic_write_json(
                    self.endpoint_file,
                    {
                        "profile": self.instance_id,
                        "endpoint": self.endpoint,
                        "pid": os.getpid(),
                        "kind": "ephemeral" if self.ephemeral else "persistent",
                    },
                )
                log(f"instance {self.instance_id} ready at {self.endpoint}")
                last_save = time.time()
                last_reap = time.time()
                while not self.stop_requested.is_set():
                    self.drain_commands(context)
                    now = time.time()
                    if now - last_save >= STATE_SAVE_INTERVAL:
                        self.save_state(context)
                        last_save = now
                    if now - last_reap >= 600:
                        self.reap(context, now)
                        last_reap = now
                    time.sleep(1)
                self.save_state(context)
        except Exception as error:  # pragma: no cover - reported via status
            self.error = str(error)
            log(f"instance {self.instance_id} failed: {error}")
        finally:
            self.exit_code = 0
            try:
                os.unlink(self.endpoint_file)
            except OSError:
                pass
            log(f"instance {self.instance_id} exited")

    def on_page(self, page):
        self.pages[page] = {"keepalive": False, "idle_since": time.time()}
        page.on("framenavigated", lambda navigated: self.touch(navigated))
        page.on("close", lambda closed: self.pages.pop(closed, None))

    def touch(self, page):
        entry = self.pages.get(page)
        if entry is not None:
            entry["idle_since"] = time.time()

    def save_state(self, context):
        if not self.state_path:
            return
        try:
            context.storage_state(path=self.state_path)
            os.chmod(self.state_path, 0o600)
            log(f"instance {self.instance_id} saved storage state")
        except Exception as error:
            log(f"instance {self.instance_id} state save failed: {error}")

    def drain_commands(self, context):
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                return
            action = command.get("action")
            if action == "close_tabs":
                pages = [page for page, meta in self.pages.items() if not meta.get("keepalive")]
                for page in pages:
                    try:
                        page.close()
                    except Exception:
                        pass
                command["result"] = len(pages)

    def close_tabs(self):
        command = {"action": "close_tabs"}
        self.commands.put(command)
        deadline = time.time() + 15
        while time.time() < deadline:
            if "result" in command:
                return command["result"]
            time.sleep(0.2)
        return None

    def reap(self, context, now):
        for page, meta in list(self.pages.items()):
            if meta.get("keepalive"):
                continue
            pinned = False
            try:
                name = page.evaluate("() => window.name")
                pinned = isinstance(name, str) and name.startswith(PIN_PREFIX)
            except Exception:
                pass
            if pinned:
                continue
            if now - meta.get("idle_since", now) > TAB_TTL:
                log(f"instance {self.instance_id} closing idle tab {page.url}")
                try:
                    page.close()
                except Exception:
                    pass
        if self.ephemeral and now - self.started > TEMP_IDLE_TTL:
            live = [p for p, m in self.pages.items() if not m.get("keepalive")]
            if not live:
                log(f"instance {self.instance_id} idle; shutting down")
                self.request_stop()


class Manager:
    def __init__(self):
        self.instances = {}
        self.lock = threading.Lock()
        self.next_port = EPHEMERAL_PORT_BASE
        os.makedirs(BROWSER_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

    def start_persistent(self):
        for name, port in PERSISTENT.items():
            state_path = os.path.join(PROFILE_DIR, f"{name}.state.json")
            instance = Instance(name, port, state_path=state_path)
            with self.lock:
                self.instances[name] = instance
            instance.start()

    def supervise(self, stop_event):
        while not stop_event.is_set():
            with self.lock:
                instances = list(self.instances.values())
            for instance in instances:
                if not instance.is_alive() and not instance.stop_requested.is_set():
                    log(f"instance {instance.instance_id} died; restarting")
                    replacement = Instance(
                        instance.instance_id,
                        instance.port,
                        state_path=instance.state_path,
                        seed_state=instance.seed_state,
                        ephemeral=instance.ephemeral,
                    )
                    with self.lock:
                        self.instances[instance.instance_id] = replacement
                    replacement.start()
            stop_event.wait(5)

    def allocate_port(self):
        with self.lock:
            self.next_port += 1
            return self.next_port

    def spawn_ephemeral(self, seed_profile=None):
        instance_id = f"temp-{secrets.token_hex(4)}"
        seed_state = None
        if seed_profile:
            candidate = os.path.join(PROFILE_DIR, f"{seed_profile}.state.json")
            if os.path.exists(candidate):
                seed_state = candidate
        instance = Instance(
            instance_id,
            self.allocate_port(),
            seed_state=seed_state,
            ephemeral=True,
        )
        with self.lock:
            self.instances[instance_id] = instance
        instance.start()
        deadline = time.time() + 60
        while time.time() < deadline:
            if instance.endpoint or instance.error:
                break
            time.sleep(0.5)
        if instance.error:
            with self.lock:
                self.instances.pop(instance_id, None)
            raise RuntimeError(instance.error)
        return instance

    def stop_instance(self, instance_id):
        with self.lock:
            instance = self.instances.get(instance_id)
        if instance is None:
            return False
        if not instance.ephemeral:
            return False
        instance.request_stop()
        deadline = time.time() + 30
        while time.time() < deadline and instance.is_alive():
            time.sleep(0.5)
        with self.lock:
            self.instances.pop(instance_id, None)
        return True

    def status(self):
        with self.lock:
            return [instance.status() for instance in self.instances.values()]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log(fmt % args)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/browsers":
            self.send_json(200, {"browsers": self.server.manager.status()})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or "0")
        payload = {}
        if length:
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.send_json(400, {"error": "invalid json"})
                return
        manager = self.server.manager
        if path == "/browsers":
            try:
                instance = manager.spawn_ephemeral(payload.get("seed_profile"))
            except RuntimeError as error:
                self.send_json(502, {"error": str(error)})
                return
            self.send_json(200, instance.status())
            return
        match = re.fullmatch(r"/browsers/([A-Za-z0-9_-]+)/close-tabs", path)
        if match:
            with manager.lock:
                instance = manager.instances.get(match.group(1))
            if instance is None:
                self.send_json(404, {"error": "unknown browser"})
                return
            closed = instance.close_tabs()
            self.send_json(200, {"closed": closed})
            return
        self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/browsers/([A-Za-z0-9_-]+)", path)
        if not match:
            self.send_json(404, {"error": "not found"})
            return
        if self.server.manager.stop_instance(match.group(1)):
            self.send_json(200, {"stopped": match.group(1)})
        else:
            self.send_json(409, {"error": "not an ephemeral browser"})


def main():
    manager = Manager()
    manager.start_persistent()
    server = ThreadingHTTPServer((MANAGER_BIND, MANAGER_PORT), Handler)
    server.manager = manager
    server.daemon_threads = True
    stop_event = threading.Event()

    def _stop(*_):
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    supervisor = threading.Thread(target=manager.supervise, args=(stop_event,), daemon=True)
    supervisor.start()
    log(f"manager listening on {MANAGER_BIND}:{MANAGER_PORT}")
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        with manager.lock:
            instances = list(manager.instances.values())
        for instance in instances:
            instance.request_stop()
        for instance in instances:
            instance.join(timeout=20)
        log("manager exited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
