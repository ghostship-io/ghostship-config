#!/usr/bin/env python3
"""Home Depot journey runner for the CDP compatibility matrix.

Runs the same browsing journey with a chosen driver, records page results
and teardown, and takes evidence screenshots through Pelorus (never a second
CDP connection).
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cdp_client  # noqa: E402

CHROME = "/usr/bin/google-chrome-stable"
PORT = 9330
STEPS = [
    ("home", "https://www.homedepot.com/"),
    ("search", "https://www.homedepot.com/s/cordless%20drill"),
]
FALLBACK_PRODUCT = "https://www.homedepot.com/p/DEWALT-20V-MAX-Cordless-Drill-Driver-Kit-DCD771C2/203040567"


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


def screenshot(out_dir, name):
    try:
        with urllib.request.urlopen("http://127.0.0.1:5100/api/desktop/screenshot", timeout=30) as response:
            data = json.loads(response.read())["data"]
        import base64

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
                count = connection.execute("select count(*) from cookies where host_key like '%homedepot%'").fetchone()[0]
                connection.close()
                return count
            except Exception:
                continue
    return None


def classify(text):
    lowered = (text or "").lower()
    if "error page" in lowered or "something went wrong" in lowered:
        return "error_page"
    if "access denied" in lowered or "blocked" in lowered:
        return "blocked"
    if "captcha" in lowered or "verify you are human" in lowered:
        return "challenge"
    return "ok"


def product_stats(text):
    prices = len(re.findall(r"\$\s?\d", text or ""))
    product_links = len(re.findall(r"/p/", text or ""))
    return {"prices": prices, "product_links": product_links, "chars": len(text or "")}


def run_control(args, out_dir, results):
    profile = str(pathlib.Path(args.profile).resolve())
    url = STEPS[1][1]
    process = launch(profile, 0, url)
    time.sleep(32)
    shot = screenshot(out_dir, "control-search")
    results.append(
        {
            "driver": "control",
            "step": "search",
            "cdp": False,
            "screenshot": shot,
            "note": "read the screenshot for the grid; no CDP was used",
        }
    )
    stop(process, profile)
    process = launch(profile, 0, FALLBACK_PRODUCT)
    time.sleep(28)
    results.append(
        {
            "driver": "control",
            "step": "product",
            "url": FALLBACK_PRODUCT,
            "screenshot": screenshot(out_dir, "control-product"),
        }
    )
    stop(process, profile)
    results[-1]["teardown"] = "chrome stopped"
    results[-1]["cookies_hd"] = cookie_count(profile)
    return results


def run_bladebro(args, out_dir, results):
    profile = str(pathlib.Path(args.profile).resolve())
    home = pathlib.Path(args.out) / "bladebro-home"
    home.mkdir(parents=True, exist_ok=True)
    process = launch(profile, PORT, STEPS[0][1])
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            cdp_client.http_json(PORT, "/json/version", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    time.sleep(3)
    for index, (name, url) in enumerate(STEPS):
        code, output = bladebro(home, ["nav", url, "--port", str(PORT)])
        time.sleep(4)
        shot = screenshot(out_dir, f"bladebro-{name}")
        results.append(
            {
                "driver": "bladebro",
                "step": name,
                "exit": code,
                "result": classify(output),
                "text_head": output[:400],
                "screenshot": shot,
                "cdp_domains": "bladebro real-lane attach (no Runtime.enable observed in C2)",
            }
        )
    code, output = bladebro(home, ["see", "extract", "auto", "--port", str(PORT)])
    results.append({"driver": "bladebro", "step": "extract", "exit": code, "stats": product_stats(output), "text_head": output[:500]})
    match = re.search(r'"url":\s*"([^"]+/p/[^"]+)"', output)
    product_url = match.group(1) if match else FALLBACK_PRODUCT
    code, output = bladebro(home, ["nav", product_url, "--port", str(PORT)])
    time.sleep(4)
    results.append(
        {
            "driver": "bladebro",
            "step": "product",
            "url": product_url,
            "exit": code,
            "result": classify(output),
            "stats": product_stats(output),
            "text_head": output[:400],
            "screenshot": screenshot(out_dir, "bladebro-product"),
        }
    )
    code, output = bladebro(home, ["act", "reload", "--port", str(PORT)])
    results.append({"driver": "bladebro", "step": "reload", "exit": code, "result": classify(output), "text_head": output[:200]})
    stop(process, profile)
    results.append({"driver": "bladebro", "step": "teardown", "chrome_alive": False, "cookies_hd": cookie_count(profile)})
    return results


def run_raw(args, out_dir, results):
    profile = str(pathlib.Path(args.profile).resolve())
    process = launch(profile, PORT, STEPS[0][1])
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            cdp_client.http_json(PORT, "/json/version", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    time.sleep(3)
    target = cdp_client.page_target(PORT)
    ws = cdp_client.WebSocket("127.0.0.1", PORT, target["webSocketDebuggerUrl"].split(str(PORT), 1)[1])
    ws.call("Page.enable")
    for name, url in STEPS:
        ws.call("Page.navigate", {"url": url})
        time.sleep(8)
        read = ws.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
        text = read["result"].get("value") or ""
        read = ws.call("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
        title = read["result"].get("value") or ""
        results.append(
            {
                "driver": "raw",
                "step": name,
                "result": classify(title + "\n" + text),
                "title": title,
                "stats": product_stats(text),
                "text_head": text[:300],
                "screenshot": screenshot(out_dir, f"raw-{name}"),
            }
        )
    read = ws.call("Runtime.evaluate", {"expression": "(() => { const a = document.querySelector('a[href*=\"/p/\"]'); return a ? a.href : null; })()", "returnByValue": True})
    product_url = read["result"].get("value") or FALLBACK_PRODUCT
    ws.call("Page.navigate", {"url": product_url})
    time.sleep(8)
    read = ws.call("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
    title = read["result"].get("value") or ""
    read = ws.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
    text = read["result"].get("value") or ""
    results.append(
        {
            "driver": "raw",
            "step": "product",
            "url": product_url,
            "title": title,
            "result": classify(title + "\n" + text),
            "stats": product_stats(text),
            "text_head": text[:300],
            "screenshot": screenshot(out_dir, "raw-product"),
        }
    )
    ws.call("Page.reload")
    time.sleep(6)
    read = ws.call("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
    results.append({"driver": "raw", "step": "reload", "title": read["result"].get("value"), "result": classify(read["result"].get("value") or "")})
    ws.close()
    time.sleep(2)
    process.poll()
    results.append({"driver": "raw", "step": "teardown", "chrome_alive": process.poll() is None, "cookies_hd": cookie_count(profile)})
    stop(process, profile)
    return results


def main():
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
    (out_dir / f"retailer-{args.driver}.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
