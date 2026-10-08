#!/usr/bin/env python3
"""Home Depot journey runner with strict validation.

Success requires real live product links (never a fallback), distinct
products, prices, complete pages, and a working reload. Denials, challenges
and incomplete pages are classified explicitly. Drivers: bladebro, raw, and
a screenshot-only no-CDP control.
"""

import argparse
import json
import os
import pathlib
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
import base64

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cdp_client  # noqa: E402

CHROME = "/usr/bin/google-chrome-stable"
PORT = 9330
STEPS = [
    ("home", "https://www.homedepot.com/"),
    ("search", "https://www.homedepot.com/s/cordless%20drill"),
]

ERROR_MARKERS = (
    "error page",
    "something went wrong",
    "oops",
    "403",
    "forbidden",
    "access denied",
)
BLOCKED_MARKERS = ("blocked", "press & hold", "press and hold", "unusual traffic")
CHALLENGE_MARKERS = ("captcha", "verify you are human", "are you a robot", "checking your browser")
COMPLETE_MARKERS = {
    "search": ("results", "add to cart", "all filters", "brand", "shop all"),
    "product": ("add to cart", "model#", "specifications", "$"),
}

STRUCTURED_JS = """(() => {
  const anchors = [...document.querySelectorAll('a[href]')];
  const products = [...new Set(anchors.map(a => a.href).filter(h => h.includes('/p/')))];
  const text = document.body ? document.body.innerText : '';
  return JSON.stringify({
    title: document.title,
    url: location.href,
    text: text.slice(0, 5000),
    products: products.slice(0, 30),
    prices: (text.match(/\\$\\s?\\d/g) || []).length,
  });
})()"""


def bladebro_env(home):
    env = dict(os.environ)
    env["HOME"] = "/config"
    env["BLADE_HOME"] = str(home)
    env["BLADE_LANE"] = "real"
    env["BLADE_NO_UPDATE_CHECK"] = "1"
    env["CHROME_PATH"] = CHROME
    return env


def bladebro(home, args, timeout=240):
    result = subprocess.run(
        ["/usr/local/bin/bladebro", *args],
        env=bladebro_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout


def launch(profile, port, url):
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
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def stop(process, profile):
    if process is not None and process.poll() is None:
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


def wait_ready(port, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            cdp_client.http_json(port, "/json/version", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def screenshot(out_dir, name):
    try:
        with urllib.request.urlopen("http://127.0.0.1:5100/api/desktop/screenshot", timeout=30) as response:
            data = json.loads(response.read())["data"]
        path = pathlib.Path(out_dir) / f"{name}.png"
        path.write_bytes(base64.b64decode(data))
        return str(path)
    except Exception as error:
        return f"<screenshot failed: {error}>"


def cookie_count(profile):
    for candidate in ("Default/Cookies", "Default/Network/Cookies"):
        path = pathlib.Path(profile) / candidate
        if path.exists():
            try:
                connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                count = connection.execute(
                    "select count(*) from cookies where host_key like '%homedepot%'"
                ).fetchone()[0]
                connection.close()
                return count
            except Exception:
                continue
    return None


def page_complete(kind, text):
    markers = COMPLETE_MARKERS.get(kind)
    if markers is None:
        return True
    lowered = (text or "").lower()
    return any(marker in lowered for marker in markers)


def classify(text, kind=None):
    lowered = (text or "").lower()
    if any(marker in lowered for marker in ERROR_MARKERS):
        return "error_page"
    if any(marker in lowered for marker in BLOCKED_MARKERS):
        return "blocked"
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return "challenge"
    if not page_complete(kind, text):
        return "incomplete"
    return "ok"


def stats(text, products=None):
    text = text or ""
    unique = list(dict.fromkeys(products or []))
    return {
        "prices": len(re.findall(r"\$\s?\d", text)),
        "unique_products": len(unique),
        "product_urls": unique[:10],
        "chars": len(text),
    }


def title_from_nav(output):
    match = re.search(r"title:\s*(.+)", output or "")
    return match.group(1).strip() if match else None


def parse_bladebro_extract(output):
    start = (output or "").find("{")
    if start < 0:
        return {"items": [], "products": []}
    try:
        data = json.loads(output[start:])
    except ValueError:
        return {"items": [], "products": []}
    items = data.get("items", [])
    products = []
    for item in items:
        url = item.get("url") or ""
        if "/p/" in url:
            products.append(url)
    return {"items": items, "products": list(dict.fromkeys(products))}


def run_bladebro(args, out_dir, results):
    profile = str(pathlib.Path(args.profile).resolve())
    home = pathlib.Path(args.out) / "bladebro-home"
    home.mkdir(parents=True, exist_ok=True)
    process = launch(profile, PORT, STEPS[0][1])
    ready = wait_ready(PORT)
    time.sleep(3)
    if not ready:
        results.append({"driver": "bladebro", "step": "startup", "result": "chrome_not_ready"})
        stop(process, profile)
        return results

    code, output = bladebro(home, ["nav", STEPS[0][1], "--port", str(PORT)])
    time.sleep(4)
    home_text = send_bladebro_text(home)
    results.append(
        {
            "driver": "bladebro",
            "step": "home",
            "exit": code,
            "result": classify(title_from_nav(output) + "\n" + home_text, None),
            "title": title_from_nav(output),
            "stats": stats(home_text),
        }
    )

    code, output = bladebro(home, ["nav", STEPS[1][1], "--port", str(PORT)])
    time.sleep(5)
    search_text = send_bladebro_text(home)
    search_title = title_from_nav(output)
    code, extract_output = bladebro(home, ["see", "extract", "auto", "--port", str(PORT)])
    parsed = parse_bladebro_extract(extract_output)
    extraction_ok = len(parsed["products"]) >= 3 and any(item.get("price") for item in parsed["items"])
    search_result = classify(search_title + "\n" + search_text, "search")
    if search_result == "incomplete" and extraction_ok:
        search_result = "ok"
    results.append(
        {
            "driver": "bladebro",
            "step": "search",
            "exit": code,
            "result": search_result,
            "title": search_title,
            "stats": stats(search_text, parsed["products"]),
            "extraction_ok": extraction_ok,
            "screenshot": screenshot(out_dir, "bladebro-search"),
        }
    )

    if parsed["products"]:
        product_url = parsed["products"][0]
        code, output = bladebro(home, ["nav", product_url, "--port", str(PORT)])
        time.sleep(4)
        product_text = send_bladebro_text(home)
        results.append(
            {
                "driver": "bladebro",
                "step": "product",
                "exit": code,
                "url": product_url,
                "result": classify(title_from_nav(output) + "\n" + product_text, "product"),
                "title": title_from_nav(output),
                "stats": stats(product_text),
                "screenshot": screenshot(out_dir, "bladebro-product"),
            }
        )
    else:
        results.append(
            {
                "driver": "bladebro",
                "step": "product",
                "result": "skipped_no_product",
                "note": "no live product link was extracted; no fallback is used",
            }
        )

    code, output = bladebro(home, ["act", "reload", "--port", str(PORT)])
    time.sleep(5)
    reload_text = send_bladebro_text(home)
    results.append(
        {
            "driver": "bladebro",
            "step": "reload",
            "exit": code,
            "result": classify(title_from_nav(output) + "\n" + reload_text, "product"),
        }
    )
    stop(process, profile)
    results.append({"driver": "bladebro", "step": "teardown", "cookies_hd": cookie_count(profile)})
    return results


def send_bladebro_text(home):
    code, output = bladebro(home, ["see", "content", "--port", str(PORT)], timeout=120)
    if code != 0:
        return ""
    return output


def run_raw(args, out_dir, results):
    profile = str(pathlib.Path(args.profile).resolve())
    process = launch(profile, PORT, STEPS[0][1])
    ready = wait_ready(PORT)
    time.sleep(3)
    if not ready:
        results.append({"driver": "raw", "step": "startup", "result": "chrome_not_ready"})
        stop(process, profile)
        return results
    target = cdp_client.page_target(PORT)
    ws = cdp_client.WebSocket("127.0.0.1", PORT, target["webSocketDebuggerUrl"].split(str(PORT), 1)[1])
    ws.call("Page.enable")

    def read_page():
        result = ws.call(
            "Runtime.evaluate",
            {"expression": STRUCTURED_JS, "returnByValue": True},
        )
        return json.loads(result["result"]["value"])

    for name, url in STEPS:
        ws.call("Page.navigate", {"url": url})
        time.sleep(8)
        page = read_page()
        results.append(
            {
                "driver": "raw",
                "step": name,
                "result": classify(page["title"] + "\n" + page["text"], name),
                "title": page["title"],
                "url": page["url"],
                "stats": stats(page["text"], page["products"]),
                "screenshot": screenshot(out_dir, f"raw-{name}"),
            }
        )
        if name == "search":
            products = page["products"]
            extraction_ok = len(products) >= 3 and page["prices"] > 0
            results[-1]["extraction_ok"] = extraction_ok

    page = read_page()
    products = page["products"]
    if products:
        ws.call("Page.navigate", {"url": products[0]})
        time.sleep(8)
        product = read_page()
        results.append(
            {
                "driver": "raw",
                "step": "product",
                "url": products[0],
                "result": classify(product["title"] + "\n" + product["text"], "product"),
                "title": product["title"],
                "stats": stats(product["text"]),
                "screenshot": screenshot(out_dir, "raw-product"),
            }
        )
    else:
        results.append(
            {
                "driver": "raw",
                "step": "product",
                "result": "skipped_no_product",
                "note": "no live product link was extracted; no fallback is used",
            }
        )

    ws.call("Page.reload")
    time.sleep(6)
    page = read_page()
    results.append(
        {
            "driver": "raw",
            "step": "reload",
            "result": classify(page["title"] + "\n" + page["text"], "product"),
            "title": page["title"],
        }
    )
    ws.close()
    time.sleep(2)
    alive = process.poll() is None
    results.append({"driver": "raw", "step": "teardown", "chrome_alive_after_detach": alive, "cookies_hd": cookie_count(profile)})
    stop(process, profile)
    return results


def run_control(args, out_dir, results):
    profile = str(pathlib.Path(args.profile).resolve())
    process = launch(profile, 0, STEPS[0][1])
    time.sleep(24)
    results.append(
        {
            "driver": "control",
            "step": "home",
            "screenshot": screenshot(out_dir, "control-home"),
            "note": "screenshot-only baseline; no CDP",
        }
    )
    stop(process, profile)
    process = launch(profile, 0, STEPS[1][1])
    time.sleep(30)
    results.append(
        {
            "driver": "control",
            "step": "search",
            "screenshot": screenshot(out_dir, "control-search"),
            "note": "screenshot-only baseline; no CDP",
        }
    )
    stop(process, profile)
    results.append(
        {
            "driver": "control",
            "step": "teardown",
            "note": "product step not applicable to the screenshot-only control",
            "cookies_hd": cookie_count(profile),
        }
    )
    return results


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", choices=["control", "bladebro", "raw"], required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    if args.driver == "control":
        run_control(args, out_dir, results)
    elif args.driver == "bladebro":
        run_bladebro(args, out_dir, results)
    else:
        run_raw(args, out_dir, results)
    steps = {row["step"]: row for row in results}
    if args.driver == "control":
        journey_ok = None
    else:
        journey_ok = all(
            steps.get(name, {}).get("result") == "ok" for name in ("home", "search", "product", "reload")
        )
        journey_ok = journey_ok and bool(steps.get("search", {}).get("extraction_ok"))
    summary = {"driver": args.driver, "journey_ok": journey_ok, "steps": results}
    (out_dir / f"retailer-{args.driver}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if journey_ok else 1


if __name__ == "__main__":
    sys.exit(main())
