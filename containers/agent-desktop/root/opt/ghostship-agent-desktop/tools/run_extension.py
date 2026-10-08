#!/usr/bin/env python3
"""Evaluate a Chrome extension as a non-CDP automation transport.

Launches Chrome with the bundled unpacked extension (no DevTools port) and
drives it through the local command channel: navigate, evaluate page state,
DOM-click a product link, reload, and a bot-detector page. Reports whether
Chrome still honours --load-extension in this build.
"""

import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cdp_client  # noqa: E402  (only for wait helpers; no CDP connection is made)

CHROME = "/usr/bin/google-chrome-stable"
EXT_DIR = pathlib.Path(__file__).resolve().parent / "ext"
PORT = 9977
CHANNEL = {"hello": None, "queue": [], "results": {}, "lock": threading.Lock()}
COUNTER = {"id": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/ext/next"):
            with CHANNEL["lock"]:
                if CHANNEL["queue"]:
                    self._send(200, CHANNEL["queue"].pop(0))
                else:
                    self._send(204)
            return
        self._send(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        if self.path.startswith("/ext/hello"):
            with CHANNEL["lock"]:
                CHANNEL["hello"] = payload
            self._send(200, {"ok": True})
            return
        if self.path.startswith("/ext/result"):
            with CHANNEL["lock"]:
                CHANNEL["results"][payload.get("id")] = payload
            self._send(200, {"ok": True})
            return
        self._send(404)


def start_channel():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def send_command(op, timeout=90, **fields):
    COUNTER["id"] += 1
    command = {"id": COUNTER["id"], "op": op, **fields}
    with CHANNEL["lock"]:
        CHANNEL["queue"].append(command)
    deadline = time.time() + timeout
    while time.time() < deadline:
        with CHANNEL["lock"]:
            if command["id"] in CHANNEL["results"]:
                return CHANNEL["results"].pop(command["id"])["result"]
        time.sleep(0.3)
    return {"error": "timeout"}


def launch(profile):
    command = [
        CHROME,
        f"--user-data-dir={profile}",
        f"--load-extension={EXT_DIR}",
        f"--disable-extensions-except={EXT_DIR}",
        "--ozone-platform=wayland",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
        "--password-store=basic",
        "--lang=en-US",
        "--window-size=1600,900",
        "about:blank",
    ]
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop(process, profile):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            process.wait(timeout=5)
    subprocess.run(["pkill", "-f", "--", f"--user-data-dir={profile}"], check=False)


def screenshot(out_dir, name):
    try:
        with urllib.request.urlopen("http://127.0.0.1:5100/api/desktop/screenshot", timeout=30) as response:
            data = json.loads(response.read())["data"]
        path = pathlib.Path(out_dir) / f"{name}.png"
        path.write_bytes(base64.b64decode(data))
        return str(path)
    except Exception as error:
        return f"<screenshot failed: {error}>"


def classify(text):
    lowered = (text or "").lower()
    if "error page" in lowered or "something went wrong" in lowered:
        return "error_page"
    if "access denied" in lowered:
        return "blocked"
    if "captcha" in lowered or "verify you are human" in lowered:
        return "challenge"
    return "ok"


def stats(text):
    return {
        "prices": len(re.findall(r"\$\s?\d", text or "")),
        "product_links": len(re.findall(r"/p/", text or "")),
        "chars": len(text or ""),
    }


SESSION_ENV_PATH = "/config/agent-desktop/session-env"
SESSION_KEYS = (
    "WAYLAND_DISPLAY",
    "DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "QT_ACCESSIBILITY",
    "GTK_MODULES",
    "XDG_CURRENT_DESKTOP",
    "QT_LINUX_ACCESSIBILITY_ALWAYS_ON",
)


def load_session_env():
    """Make the tools usable from podman exec or a timer, not just SSH."""
    path = pathlib.Path(SESSION_ENV_PATH)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in SESSION_KEYS:
            os.environ.setdefault(key, value)


def main():
    load_session_env()
    profile = sys.argv[1]
    out_dir = pathlib.Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    start_channel()
    results = []
    process = launch(profile)

    deadline = time.time() + 45
    while time.time() < deadline:
        with CHANNEL["lock"]:
            if CHANNEL["hello"]:
                break
        time.sleep(0.5)
    with CHANNEL["lock"]:
        hello = CHANNEL["hello"]
    results.append({"step": "load_extension", "loaded": bool(hello), "hello": hello})
    if not hello:
        results.append(
            {
                "step": "verdict",
                "result": "extension transport unavailable",
                "note": "Chrome did not start the unpacked extension; --load-extension may be disabled in this build, or the flag needs enterprise policy",
            }
        )
        stop(process, profile)
        (out_dir / "extension.json").write_text(json.dumps(results, indent=2))
        print(json.dumps(results, indent=2))
        return 1

    journey = [
        ("home", "https://www.homedepot.com/"),
        ("search", "https://www.homedepot.com/s/cordless%20drill"),
    ]
    for name, url in journey:
        result = send_command("navigate", url=url)
        time.sleep(5)
        text = send_command("evaluate", name="text").get("value") or ""
        results.append(
            {
                "step": name,
                "nav": result,
                "result": classify((result.get("title") or "") + "\n" + text),
                "stats": stats(text),
                "text_head": text[:300],
                "screenshot": screenshot(out_dir, f"extension-{name}"),
            }
        )

    product_url = send_command("evaluate", name="first_product").get("value")
    results.append({"step": "first_product", "url": product_url})
    if product_url:
        result = send_command("navigate", url=product_url)
        time.sleep(4)
        text = send_command("evaluate", name="text").get("value") or ""
        results.append(
            {
                "step": "product",
                "nav": result,
                "result": classify((result.get("title") or "") + "\n" + text),
                "stats": stats(text),
                "text_head": text[:300],
                "screenshot": screenshot(out_dir, "extension-product"),
            }
        )

    clicked = send_command("click_selector", selector='a[href*="/p/"]', timeout=30)
    results.append({"step": "dom_click_product", "result": clicked})
    time.sleep(4)

    reload_result = send_command("reload")
    results.append({"step": "reload", "result": reload_result})

    result = send_command("navigate", url="https://deviceandbrowserinfo.com/are_you_a_bot")
    time.sleep(18)
    text = send_command("evaluate", name="text").get("value") or ""
    results.append(
        {
            "step": "deviceinfo",
            "nav": result,
            "human": "you are human" in text.lower(),
            "bot": "you are a bot" in text.lower(),
            "text_head": text[:400],
            "screenshot": screenshot(out_dir, "extension-deviceinfo"),
        }
    )

    stop(process, profile)
    (out_dir / "extension.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
