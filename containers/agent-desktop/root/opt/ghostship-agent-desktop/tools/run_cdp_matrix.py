#!/usr/bin/env python3
"""CDP detection experiment harness for the Ghostship agent desktop.

Serves the local diagnostic page, launches one isolated Chrome per variant
from a closed seed profile, runs exactly one CDP operation set through the
minimal client, and records what the page reports. Observation uses the
page's own reports and Pelorus screenshots, never a second CDP connection.
"""

import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cdp_client  # noqa: E402

BASE_DIR = pathlib.Path("/config/agent-desktop/cdp-matrix")
CHROME = "/usr/bin/google-chrome-stable"
PORT_BASE = 9300
REPORT_PORT = 9977

VARIANTS = {
    "A0": [],
    "A1": [],
    "A2": ["http"],
    "A3": ["http", "browser", "browser_version"],
    "A4": ["http", "browser", "targets"],
    "A5": ["http", "page_ws"],
    "A6": ["http", "browser", "attach"],
    "A7": ["http", "browser", "attach", "page_enable"],
    "A8": ["http", "browser", "attach", "network_enable"],
    "A9": ["http", "browser", "attach", "dom_enable"],
    "A10": ["http", "browser", "attach", "runtime_evaluate"],
    "A11": ["http", "browser", "attach", "accessibility"],
    "A12": ["http", "browser", "attach", "input"],
    "A13": ["http", "browser", "attach", "runtime_enable"],
    "B7P": ["http", "page_ws", "page_enable"],
}

REPORTS = {}
REPORTS_LOCK = threading.Lock()
OUT_DIR = None


class DiagHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/diag.html"):
            page = pathlib.Path(__file__).resolve().parent / "diag.html"
            self._send(200, page.read_text(encoding="utf-8"), "text/html")
            return
        self._send(404, "{}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length)
        run = "unknown"
        if "?run=" in self.path:
            run = self.path.split("?run=", 1)[1].split("&", 1)[0]
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            self._send(400, "{}")
            return
        with REPORTS_LOCK:
            REPORTS.setdefault(run, []).append(payload)
            if OUT_DIR is not None:
                with open(OUT_DIR / "reports.jsonl", "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"run": run, "wall": time.time(), "payload": payload}) + "\n")
        self._send(200, "{}")


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", REPORT_PORT), DiagHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def kill_profile_chrome(profile):
    subprocess.run(["pkill", "-f", "--", f"--user-data-dir={profile}"], check=False)
    time.sleep(1)


def launch_chrome(profile, port, url, log_name="chrome"):
    command = [
        CHROME,
        f"--user-data-dir={profile}",
        "--ozone-platform=wayland",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-crash-restore-bubble",
        "--password-store=basic",
        "--lang=en-US",
        "--window-size=1600,900",
    ]
    if port:
        command.append(f"--remote-debugging-port={port}")
    command.append(url)
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = open(log_dir / f"{log_name}.log", "ab")
    return subprocess.Popen(
        command,
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop_chrome(process, profile):
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
    kill_profile_chrome(profile)


def wait_ready(port, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cdp_client.http_json(port, "/json/version", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def make_seed(seed_dir):
    if seed_dir.exists():
        return
    seed_dir.parent.mkdir(parents=True, exist_ok=True)
    port = PORT_BASE - 1
    process = launch_chrome(str(seed_dir), port, f"http://127.0.0.1:{REPORT_PORT}/diag.html?run=seed", log_name="seed")
    wait_ready(port, timeout=30)
    time.sleep(12)
    stop_chrome(process, str(seed_dir))
    for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (seed_dir / lock).unlink()
        except OSError:
            pass
    print(f"[matrix] seed profile created at {seed_dir}", flush=True)


def run_variant(variant, ops, seed_dir, keep_profile=False):
    profile = BASE_DIR / "profiles" / variant
    if profile.exists():
        shutil.rmtree(profile)
    profile.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-a", "--reflink=auto", str(seed_dir), str(profile)], check=True)

    port = 0 if variant == "A0" else PORT_BASE + list(VARIANTS).index(variant)
    run_id = variant
    with REPORTS_LOCK:
        REPORTS.pop(run_id, None)

    process = launch_chrome(str(profile), port, f"http://127.0.0.1:{REPORT_PORT}/diag.html?run={run_id}", log_name=f"{variant}")
    ready = wait_ready(port, timeout=40) if port else True
    if variant == "A0":
        time.sleep(10)
    time.sleep(4)

    t0 = time.time()
    executed = []
    error = None
    if ops:
        try:
            executed = cdp_client.run_operations(port, set(ops), None)
        except Exception as exc:
            error = str(exc)
    t1 = time.time()
    time.sleep(5)

    with REPORTS_LOCK:
        reports = list(REPORTS.get(run_id, []))
    stop_chrome(process, str(profile))

    def detected(report):
        return bool(report.get("cdpMain") or report.get("cdpWorker"))

    baseline = [r for r in reports if r.get("t", 0) < t0 * 1000]
    after = [r for r in reports if r.get("t", 0) >= t0 * 1000]
    first_fired = next((r for r in reports if detected(r)), None)
    result = {
        "variant": variant,
        "ops": ops,
        "port_open": bool(port),
        "ready": ready,
        "executed": executed,
        "error": error,
        "reports": len(reports),
        "baseline_detected": any(detected(r) for r in baseline),
        "after_detected": any(detected(r) for r in after),
        "worker_detected": any(r.get("cdpWorker") for r in reports),
        "detected_reports": sum(1 for r in reports if detected(r)),
        "samples_after": len(after),
        "first_fired_seq": first_fired.get("seq") if first_fired else None,
        "first_fired_t": first_fired.get("t") if first_fired else None,
        "op_started": t0,
        "op_ended": t1,
        "final": reports[-1] if reports else None,
    }
    if not keep_profile:
        shutil.rmtree(profile, ignore_errors=True)
    return result




CLEAN_OPS = {"http", "browser", "attach", "page_enable", "runtime_evaluate", "accessibility", "input"}

DRIVERS = {
    "C1": {"launch": True, "kind": "raw_clean"},
    "C2": {"launch": True, "kind": "bladebro_attach"},
    "C4": {"launch": False, "kind": "bladebro_profile"},
}


def bladebro_env(home):
    env = dict(os.environ)
    env["HOME"] = "/config"
    env["BLADE_HOME"] = str(home)
    env["BLADE_LANE"] = "real"
    env["BLADE_NO_UPDATE_CHECK"] = "1"
    env["CHROME_PATH"] = CHROME
    return env


def run_bladebro(home, args, timeout=180):
    command = ["/usr/local/bin/bladebro", *args]
    result = subprocess.run(
        command,
        env=bladebro_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout[-800:]


def run_driver_variant(variant, seed_dir, keep_profile=False):
    spec = DRIVERS[variant]
    profile = BASE_DIR / "profiles" / variant
    blade_home = BASE_DIR / "bladebro" / variant
    if profile.exists():
        shutil.rmtree(profile)
    profile.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-a", "--reflink=auto", str(seed_dir), str(profile)], check=True)
    if blade_home.exists():
        shutil.rmtree(blade_home)
    blade_home.mkdir(parents=True, exist_ok=True)

    run_id = variant
    with REPORTS_LOCK:
        REPORTS.pop(run_id, None)
    diag_url = f"http://127.0.0.1:{REPORT_PORT}/diag.html?run={run_id}"

    process = None
    port = 0
    output = ""
    error = None
    executed = []
    ready = False
    t0 = time.time()
    if spec["launch"]:
        port = PORT_BASE + 20
        process = launch_chrome(str(profile), port, diag_url)
        ready = wait_ready(port, timeout=40)
        time.sleep(4)
        t0 = time.time()
        try:
            if spec["kind"] == "raw_clean":
                executed = cdp_client.run_operations(port, set(CLEAN_OPS), None)
                target = cdp_client.page_target(port)
                ws = cdp_client.WebSocket("127.0.0.1", port, target["webSocketDebuggerUrl"].split(str(port), 1)[1])
                read = ws.call("Runtime.evaluate", {"expression": "document.body.innerText.length", "returnByValue": True})
                ws.close()
                executed.append(f"Runtime.evaluate:body.length={read['result']['value']}")
            elif spec["kind"] == "bladebro_attach":
                code, output = run_bladebro(blade_home, ["see", "content", "--port", str(port)])
                executed.append(f"bladebro see content --port {port} exit={code}")
        except Exception as exc:
            error = str(exc)
    else:
        try:
            code1, out1 = run_bladebro(blade_home, ["rb", "mode", "profile"])
            code2, out2 = run_bladebro(blade_home, ["rb", "profile", str(profile)])
            code3, out3 = run_bladebro(blade_home, ["nav", diag_url])
            executed.append(f"rb mode profile exit={code1}; rb profile exit={code2}; nav exit={code3}")
            output = (out1 + out2 + out3)[-800:]
            ready = code3 == 0
        except Exception as exc:
            error = str(exc)

    time.sleep(6)
    if process is not None:
        stop_chrome(process, str(profile))
    if spec["kind"] == "bladebro_profile":
        try:
            run_bladebro(blade_home, ["stop"], timeout=60)
        except Exception:
            pass
        kill_profile_chrome(str(profile))

    with REPORTS_LOCK:
        reports = list(REPORTS.get(run_id, []))

    def detected(report):
        return bool(report.get("cdpMain") or report.get("cdpWorker"))

    after = [r for r in reports if r.get("t", 0) >= t0 * 1000]
    result = {
        "variant": variant,
        "kind": spec["kind"],
        "ops": sorted(CLEAN_OPS) if spec["kind"] == "raw_clean" else ["bladebro"],
        "ready": ready,
        "executed": executed,
        "error": error,
        "output": output,
        "reports": len(reports),
        "baseline_detected": any(detected(r) for r in reports if r.get("t", 0) < t0 * 1000),
        "after_detected": any(detected(r) for r in after),
        "worker_detected": any(r.get("cdpWorker") for r in reports),
        "detected_reports": sum(1 for r in reports if detected(r)),
        "samples_after": len(after),
        "final": reports[-1] if reports else None,
    }
    if not keep_profile:
        shutil.rmtree(profile, ignore_errors=True)
    return result




def run_b2(seed_dir):
    profiles = []
    processes = []
    try:
        for name in ("B2a", "B2b"):
            profile = BASE_DIR / "profiles" / name
            if profile.exists():
                shutil.rmtree(profile)
            profile.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["cp", "-a", "--reflink=auto", str(seed_dir), str(profile)], check=True)
            profiles.append(profile)
        with REPORTS_LOCK:
            REPORTS.pop("B2a", None)
            REPORTS.pop("B2b", None)
        processes.append(launch_chrome(str(profiles[0]), 0, f"http://127.0.0.1:{REPORT_PORT}/diag.html?run=B2a", log_name="B2a"))
        port = PORT_BASE + 30
        processes.append(launch_chrome(str(profiles[1]), port, f"http://127.0.0.1:{REPORT_PORT}/diag.html?run=B2b", log_name="B2b"))
        if not wait_ready(port, timeout=40):
            raise RuntimeError("B2b chrome not ready")
        time.sleep(5)
        cdp_client.run_operations(port, {"http", "browser", "attach", "runtime_enable"}, None)
        time.sleep(6)
        with REPORTS_LOCK:
            reports_a = list(REPORTS.get("B2a", []))
            reports_b = list(REPORTS.get("B2b", []))
        detected = lambda r: bool(r.get("cdpMain") or r.get("cdpWorker"))
        return {
            "variant": "B2",
            "a_detected": any(detected(r) for r in reports_a),
            "b_detected": any(detected(r) for r in reports_b),
            "a_reports": len(reports_a),
            "b_reports": len(reports_b),
            "final_a": reports_a[-1] if reports_a else None,
        }
    finally:
        for process, profile in zip(processes, profiles):
            stop_chrome(process, str(profile))
        for profile in profiles:
            shutil.rmtree(profile, ignore_errors=True)


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
    global OUT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--seed", default=f"{BASE_DIR}/seed")
    parser.add_argument("--out", default=None)
    parser.add_argument("--keep-profiles", action="store_true")
    args = parser.parse_args()

    OUT_DIR = pathlib.Path(args.out) if args.out else BASE_DIR / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start_server()
    seed_dir = pathlib.Path(args.seed)
    make_seed(seed_dir)

    results = []
    for variant in args.variants.split(","):
        variant = variant.strip()
        print(f"[matrix] running {variant}", flush=True)
        if variant == "B2":
            result = run_b2(seed_dir)
        elif variant in DRIVERS:
            result = run_driver_variant(variant, seed_dir, args.keep_profiles)
        elif variant in VARIANTS:
            result = run_variant(variant, VARIANTS[variant], seed_dir, args.keep_profiles)
        else:
            continue
        results.append(result)
        print(json.dumps(result, default=str), flush=True)
        time.sleep(2)

    summary = OUT_DIR / "results.json"
    summary.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[matrix] wrote {summary}", flush=True)


if __name__ == "__main__":
    main()
