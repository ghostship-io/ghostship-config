#!/usr/bin/env python3
"""Concurrent Bladebro MCP workers against one shared Chrome.

Each worker owns one ``bladebro mcp --port`` process and one window, binds it
with ``state switch-tab``, then runs barrier-synchronised rounds of click,
clear+type, select, scroll and navigate through Bladebro. A separate CDP
connection reads every page back (one-shot evaluate; Runtime is never
enabled) and counts any unexpected or missing effect as cross-talk.

  python3 bench_bladebro.py --port 9231 --workers 4 --rounds 40
"""
from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import random
import string
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_ws import Cdp  # noqa: E402
import bench_input  # noqa: E402

PAGE = """<!doctype html><html><head><title>bb</title></head>
<body style="margin:0;height:5000px;font:16px sans-serif">
<div style="position:fixed;top:0;left:0;right:0;background:#fff;padding:8px">
<label>Query <input id=t name=q aria-label=Query></label>
<select id=s aria-label=Size><option value=o0>o0</option><option value=o1>o1</option>
<option value=o2>o2</option><option value=o3>o3</option></select>
<span id=b></span></div>
<script>
const A = new URLSearchParams(location.search).get('agent');
document.title = 'bb-' + A;
window.__log = [];
const box = document.getElementById('b');
for (let i = 0; i < 8; i++) {
  const btn = document.createElement('button'); btn.id = 'b' + i; btn.textContent = 'Button ' + i;
  btn.onclick = e => window.__log.push({k: 'click', id: btn.id, t: e.isTrusted});
  box.appendChild(btn);
}
s.onchange = () => window.__log.push({k: 'select', v: s.value});
</script></body></html>"""

OPS = ("click", "type", "select", "scroll", "navigate")


class Mcp:
    def __init__(self, argv: list[str], env: dict[str, str]):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, env=env, bufsize=1)
        self.next = 0
        self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "bench", "version": "1"}})
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")

    def request(self, method: str, params: dict) -> dict:
        self.next += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("bladebro exited")
            message = json.loads(line)
            if message.get("id") == self.next:
                if "error" in message:
                    raise RuntimeError(message["error"].get("message"))
                return message["result"]

    def tool(self, name: str, **arguments) -> str:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
        if result.get("isError"):
            raise RuntimeError(text[:300])
        return text

    def close(self) -> None:
        self.proc.stdin.close()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Handler(bench_input._Handler):
    def do_GET(self):  # noqa: N802
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve() -> int:
    import socketserver
    import threading
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


def worker_main(index, args, http_port, barrier, results):
    rng = random.Random(args.seed * 1000 + index)
    token = f"w{index}"
    lat = {op: [] for op in OPS}
    failures: list[str] = []
    crosstalk = 0
    loop = asyncio.new_event_loop()
    cdp = loop.run_until_complete(Cdp.connect(args.port))
    url = f"http://127.0.0.1:{http_port}/?agent={token}"
    target = loop.run_until_complete(cdp.send("Target.createTarget", {"url": url, "newWindow": True,
                                                                      "background": True}))["targetId"]
    session = loop.run_until_complete(cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))[
        "sessionId"]
    loop.run_until_complete(bench_input.wait_loaded(cdp, session))

    def ev(expression):
        return loop.run_until_complete(cdp.evaluate(session, expression))

    env = dict(os.environ, BLADE_LANE="real", BLADE_NO_UPDATE_CHECK="1", HOME="/config",
               BLADE_HOME=args.blade_home)
    mcp = Mcp([args.bladebro, "mcp", "--port", str(args.port)], env)
    expected_log = 0
    try:
        mcp.tool("state", op="switch-tab", target_id=target)
        barrier.wait(300)
        for round_index in range(args.rounds):
            op = OPS[round_index % len(OPS)]
            barrier.wait(300)
            t0 = time.monotonic()
            try:
                if op == "click":
                    button = f"b{rng.randrange(8)}"
                    before = ev("window.__log.length")
                    mcp.tool("act", action="click", selector=f"#{button}", slim=True)
                    expected_log += 1
                    got = ev(f"window.__log.slice({before})")
                    if got != [{"k": "click", "id": button, "t": True}]:
                        crosstalk += 1
                        failures.append(f"click {button}: {got}")
                elif op == "type":
                    text = "".join(rng.choice(string.ascii_lowercase) for _ in range(args.chars))
                    mcp.tool("act", action="clear", selector="#t", slim=True)
                    mcp.tool("act", action="type", selector="#t", text=text, slim=True)
                    value = ev("document.getElementById('t').value")
                    if value != text:
                        crosstalk += 1
                        failures.append(f"type {text!r}: {value!r}")
                elif op == "select":
                    current = ev("document.getElementById('s').value")
                    choice = rng.choice([o for o in ("o0", "o1", "o2", "o3") if o != current])
                    before = ev("window.__log.length")
                    mcp.tool("act", action="select", selector="#s", option=choice, slim=True)
                    expected_log += 1
                    got = ev(f"window.__log.slice({before})")
                    if got != [{"k": "select", "v": choice}] or ev("document.getElementById('s').value") != choice:
                        crosstalk += 1
                        failures.append(f"select {choice}: {got}")
                elif op == "scroll":
                    before = ev("scrollY")
                    mcp.tool("act", action="scroll", dy=400, slim=True)
                    deadline = time.monotonic() + 3
                    after = before
                    while time.monotonic() < deadline and after == before:
                        time.sleep(0.05)
                        after = ev("scrollY")
                    if after <= before:
                        crosstalk += 1
                        failures.append(f"scroll: {before} -> {after}")
                elif op == "navigate":
                    nav = f"{url}&n={round_index}"
                    mcp.tool("act", action="navigate", url=nav, slim=True)
                    expected_log = 0
                    if ev("location.href") != nav:
                        crosstalk += 1
                        failures.append(f"navigate: {ev('location.href')}")
            except Exception as exc:  # recorded so one failure does not hide others
                failures.append(f"{op}: {type(exc).__name__}: {str(exc)[:200]}")
            lat[op].append(time.monotonic() - t0)
        if ev("window.__log.length") != expected_log:
            crosstalk += 1
            failures.append(f"final log != {expected_log}")
    except Exception as exc:
        failures.append(f"worker: {type(exc).__name__}: {str(exc)[:200]}")
        barrier.abort()
    finally:
        mcp.close()
        loop.run_until_complete(cdp.send("Target.closeTarget", {"targetId": target}))
    results.put({"lat": lat, "failures": failures[:20], "failure_count": len(failures), "crosstalk": crosstalk,
                 "ops": sum(len(v) for v in lat.values())})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--chars", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bladebro", default="/usr/local/bin/bladebro")
    parser.add_argument("--blade-home", default="/tmp/bench-bladebro-home")
    parser.add_argument("--sentinel-port", type=int)
    parser.add_argument("--sentinel-focus-cmd")
    args = parser.parse_args()
    os.makedirs(args.blade_home, exist_ok=True)
    subprocess.run([args.bladebro, "rb", "mode", "attach"], env=dict(os.environ, BLADE_HOME=args.blade_home,
                   HOME="/config", BLADE_NO_UPDATE_CHECK="1"), capture_output=True)

    http_port = serve()
    loop = asyncio.new_event_loop()
    s_cdp, s_target, s_session = loop.run_until_complete(
        bench_input.sentinel(args.sentinel_port or args.port, bench_input.serve(), args.sentinel_focus_cmd))
    blur0 = loop.run_until_complete(s_cdp.evaluate(s_session, "window.__blur"))
    ctx = mp.get_context("fork")
    barrier, results = ctx.Barrier(args.workers), ctx.Queue()
    t0 = time.monotonic()
    procs = [ctx.Process(target=worker_main, args=(i, args, http_port, barrier, results)) for i in range(args.workers)]
    for proc in procs:
        proc.start()
    rows = [results.get(timeout=args.rounds * 120 + 600) for _ in procs]
    wall = time.monotonic() - t0
    blur1 = loop.run_until_complete(s_cdp.evaluate(s_session, "window.__blur"))
    loop.run_until_complete(s_cdp.send("Target.closeTarget", {"targetId": s_target}))
    lat = {op: [v for row in rows for v in row["lat"][op]] for op in OPS}
    ops = sum(row["ops"] for row in rows)
    summary = {"workers": args.workers, "rounds": args.rounds, "ops": ops,
               "failures": sum(row["failure_count"] for row in rows),
               "crosstalk": sum(row["crosstalk"] for row in rows), "sentinel_blur": blur1 - blur0,
               "wall_s": round(wall, 1), "ops_per_s": round(ops / wall, 2),
               "latency_ms": {op: {"p50": bench_input.pct(v, .5), "p95": bench_input.pct(v, .95)}
                              for op, v in lat.items() if v},
               "sample_failures": [f for row in rows for f in row["failures"]][:12]}
    print(json.dumps(summary, indent=1))
    return 0 if summary["failures"] == 0 and summary["crosstalk"] == 0 and summary["sentinel_blur"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
