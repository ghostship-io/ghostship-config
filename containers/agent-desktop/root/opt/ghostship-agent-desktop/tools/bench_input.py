#!/usr/bin/env python3
"""Concurrent native-input isolation benchmark for one shared Chrome.

N agent processes each open their own window in the Chrome at --port, then run
barrier-synchronised rounds of click / type / wheel / dialog / popup. Every
operation is verified by reading the page's own event log back; any event a
page did not expect is cross-talk. A sentinel "human" window, focused first,
counts blur events: any agent stealing window focus shows up there.

Modes:
  control  global lock + Page.bringToFront before input (the deployed model)
  free     no lock, no activation
  focus    like free, plus Emulation.setFocusEmulationEnabled on each page

Only clean CDP domains are used (Target, Page, Input, Emulation, one-shot
Runtime.evaluate); Runtime is never enabled.

  python3 bench_input.py --port 9230 --agents 4 --rounds 50 --mode free
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import multiprocessing as mp
import os
import random
import socketserver
import statistics
import string
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_ws import Cdp, CdpError  # noqa: E402

PAGE = """<!doctype html><html><head><title>bench</title></head>
<body style="margin:0;height:4000px;font:14px sans-serif">
<input id=t style="position:fixed;left:10px;top:10px;width:400px;height:30px">
<button id=dlg style="position:fixed;left:450px;top:10px;width:120px;height:30px">dialog</button>
<button id=pop style="position:fixed;left:600px;top:10px;width:120px;height:30px">popup</button>
<div id=pad style="position:fixed;left:10px;top:60px;width:700px;height:400px;background:#ddd"></div>
<script>
const A = new URLSearchParams(location.search).get('agent');
document.title = 'bench-' + A;
let n = 0;
window.__log = []; window.__blur = 0;
const L = e => window.__log.push(e);
pad.addEventListener('click', e => L({k: 'click', x: e.clientX, y: e.clientY, t: e.isTrusted}));
addEventListener('wheel', e => L({k: 'wheel', dy: e.deltaY, t: e.isTrusted}), {passive: true});
dlg.onclick = () => { const r = prompt('q'); L({k: 'dialog', r}); };
pop.onclick = () => { const w = window.open('/?agent=' + A + '.p' + (++n), '_blank', 'popup,width=760,height=500'); L({k: 'popup', ok: !!w}); };
addEventListener('blur', () => window.__blur++);
window.__diag = {focus: 0, keys: 0, clicks: 0};
t.addEventListener('focus', () => window.__diag.focus++);
t.addEventListener('keydown', () => window.__diag.keys++);
addEventListener('mousedown', () => window.__diag.clicks++, true);
</script></body></html>"""

OPS = ("click", "type", "wheel", "dialog", "popup")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def serve() -> int:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


async def wait_loaded(cdp: Cdp, session: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if await cdp.evaluate(session, "document.readyState === 'complete' && !!window.__log", 5) is True:
                return
        except CdpError:
            pass
        await asyncio.sleep(0.1)
    raise CdpError("page did not load")


async def click(cdp: Cdp, session: str, x: float, y: float) -> None:
    for kind in ("mousePressed", "mouseReleased"):
        await cdp.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
                       session)


async def type_text(cdp: Cdp, session: str, text: str) -> None:
    for ch in text:
        await cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch, "unmodifiedText": ch},
                       session)
        await cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch}, session)


class Agent:
    def __init__(self, index: int, args, http_port: int):
        self.index, self.args, self.http_port = index, args, http_port
        self.rng = random.Random(args.seed * 1000 + index)
        self.token = f"a{index}"
        self.lat: dict[str, list[float]] = {op: [] for op in OPS}
        self.failures: list[str] = []
        self.crosstalk = 0
        self.expected_entries = 0

    async def open_page(self, cdp: Cdp, url: str, new_window: bool = True) -> tuple[str, str]:
        target = (await cdp.send("Target.createTarget", {"url": url, "newWindow": new_window, "background": True}))[
            "targetId"]
        session = (await cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        await cdp.send("Page.enable", {}, session)
        if self.args.mode == "focus":
            await cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True}, session)
        await wait_loaded(cdp, session)
        return target, session

    async def log_len(self, session: str) -> int:
        return await self.cdp.evaluate(session, "window.__log.length")

    async def tail(self, session: str, k: int) -> list:
        return await self.cdp.evaluate(session, f"window.__log.slice(-{k})")

    async def guarded(self, lock, session: str, coro_factory):
        if self.args.mode == "control":
            await asyncio.to_thread(lock.acquire)
            try:
                await self.cdp.send("Page.bringToFront", {}, session)
                return await coro_factory()
            finally:
                lock.release()
        return await coro_factory()

    async def op_click(self, lock) -> None:
        x, y = self.rng.randint(20, 700), self.rng.randint(70, 450)
        before = await self.log_len(self.session)
        await self.guarded(lock, self.session, lambda: click(self.cdp, self.session, x, y))
        self.expected_entries += 1
        entries = await self.cdp.evaluate(self.session, f"window.__log.slice({before})")
        if entries != [{"k": "click", "x": x, "y": y, "t": True}]:
            self.crosstalk += 1
            self.failures.append(f"click: expected ({x},{y}) got {entries}")

    async def op_type(self, lock) -> None:
        text = "".join(self.rng.choice(string.ascii_letters) for _ in range(self.args.chars))
        await self.cdp.evaluate(self.session, "t.value = ''; t.blur(); true")

        async def act():
            await click(self.cdp, self.session, 200, 25)
            await type_text(self.cdp, self.session, text)
        await self.guarded(lock, self.session, act)
        value = await self.cdp.evaluate(self.session, "t.value")
        if value != text:
            self.crosstalk += 1
            self.failures.append(f"type: expected {text!r} got {value!r}")

    async def op_wheel(self, lock) -> None:
        dy = self.rng.choice((100, 200, 300))
        before = await self.log_len(self.session)
        await self.guarded(lock, self.session, lambda: self.cdp.send(
            "Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 300, "y": 300, "deltaX": 0, "deltaY": dy},
            self.session))
        self.expected_entries += 1
        deadline = time.monotonic() + 3
        entries = []
        while time.monotonic() < deadline:
            entries = await self.cdp.evaluate(self.session, f"window.__log.slice({before})")
            if entries:
                break
            await asyncio.sleep(0.02)
        if entries != [{"k": "wheel", "dy": dy, "t": True}]:
            self.crosstalk += 1
            self.failures.append(f"wheel: expected {dy} got {entries}")

    async def op_dialog(self, lock) -> None:
        answer = f"{self.token}-{self.rng.randint(0, 10 ** 6)}"
        queue = self.cdp.listen("Page.javascriptDialogOpening", self.session)
        before = await self.log_len(self.session)

        async def act():
            # The input ack waits for the modal prompt, so answer the dialog
            # while the click is still in flight.
            pending = asyncio.ensure_future(click(self.cdp, self.session, 510, 25))
            await asyncio.wait_for(queue.get(), 10)
            await self.cdp.send("Page.handleJavaScriptDialog", {"accept": True, "promptText": answer}, self.session)
            await pending
        await self.guarded(lock, self.session, act)
        self.expected_entries += 1
        await asyncio.sleep(0.05)
        entries = await self.cdp.evaluate(self.session, f"window.__log.slice({before})")
        if entries != [{"k": "dialog", "r": answer}]:
            self.crosstalk += 1
            self.failures.append(f"dialog: expected {answer} got {entries}")

    async def op_popup(self, lock) -> None:
        created = self.cdp.listen("Target.targetCreated")
        text = "".join(self.rng.choice(string.ascii_lowercase) for _ in range(self.args.chars))
        before = await self.log_len(self.session)
        popup_target = popup_session = None

        async def act():
            nonlocal popup_target, popup_session
            await click(self.cdp, self.session, 660, 25)
            deadline = time.monotonic() + 10
            while popup_target is None:
                event = await asyncio.wait_for(created.get(), max(0.1, deadline - time.monotonic()))
                info = event["params"]["targetInfo"]
                if info.get("openerId") == self.target and info.get("type") == "page":
                    popup_target = info["targetId"]
            popup_session = (await self.cdp.send("Target.attachToTarget",
                                                 {"targetId": popup_target, "flatten": True}))["sessionId"]
            if self.args.mode == "focus":
                await self.cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True}, popup_session)
            await wait_loaded(self.cdp, popup_session)
            if self.args.paint_wait:
                await self.cdp.evaluate(popup_session, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
            if self.args.mode == "control":
                await self.cdp.send("Page.bringToFront", {}, popup_session)
            await click(self.cdp, popup_session, 200, 25)
            await type_text(self.cdp, popup_session, text)
        try:
            await self.guarded(lock, self.session, act)
            self.expected_entries += 1
            value = await self.cdp.evaluate(popup_session, "t.value")
            mine = await self.cdp.evaluate(self.session, f"window.__log.slice({before})")
            if value != text or mine != [{"k": "popup", "ok": True}]:
                self.crosstalk += 1
                diag = await self.cdp.evaluate(popup_session, "JSON.stringify(window.__diag)")
                self.failures.append(f"popup: expected {text!r} got {value!r}, opener {mine}, diag {diag}")
        finally:
            self.cdp.unlisten(created)
            if popup_target:
                await self.cdp.send("Target.closeTarget", {"targetId": popup_target})

    async def recover(self) -> None:
        try:
            await self.cdp.send("Page.handleJavaScriptDialog", {"accept": False}, self.session, 5)
        except Exception:
            pass

    async def run(self, barrier, lock, results) -> None:
        try:
            await self._run(barrier, lock, results)
        except Exception as exc:
            self.failures.append(f"agent: {type(exc).__name__}: {exc}")
            results.put({"agent": self.index, "elapsed": 0, "lat": self.lat, "failures": self.failures[:20],
                         "failure_count": len(self.failures) or 1, "crosstalk": self.crosstalk,
                         "ops": sum(len(v) for v in self.lat.values())})
            barrier.abort()

    async def _run(self, barrier, lock, results) -> None:
        self.cdp = await Cdp.connect(self.args.port)
        await self.cdp.send("Target.setDiscoverTargets", {"discover": True})
        url = f"http://127.0.0.1:{self.http_port}/?agent={self.token}"
        self.target, self.session = await self.open_page(self.cdp, url)
        await asyncio.to_thread(barrier.wait, 120)
        started = time.monotonic()
        for round_index in range(self.args.rounds):
            op = OPS[round_index % len(OPS)] if self.args.ops == "all" else self.args.ops
            await asyncio.to_thread(barrier.wait, 120)
            t0 = time.monotonic()
            try:
                await asyncio.wait_for(getattr(self, f"op_{op}")(lock), self.args.op_timeout)
            except Exception as exc:  # recorded, not raised: one failure must not hide others
                self.failures.append(f"{op}: {type(exc).__name__}: {exc}")
                await self.recover()
            self.lat[op].append(time.monotonic() - t0)
        elapsed = time.monotonic() - started
        final = await self.cdp.evaluate(self.session, "window.__log.length")
        if final != self.expected_entries:
            self.crosstalk += 1
            self.failures.append(f"final log {final} != expected {self.expected_entries}")
        await self.cdp.send("Target.closeTarget", {"targetId": self.target})
        results.put({"agent": self.index, "elapsed": elapsed, "lat": self.lat, "failures": self.failures[:20],
                     "failure_count": len(self.failures), "crosstalk": self.crosstalk,
                     "ops": sum(len(v) for v in self.lat.values())})
        await self.cdp.close()


def agent_main(index, args, http_port, barrier, lock, results):
    asyncio.run(Agent(index, args, http_port).run(barrier, lock, results))


def cgroup() -> dict:
    out = {}
    for name in ("memory.current", "memory.peak", "pids.current", "pids.peak"):
        try:
            out[name] = int(open(f"/sys/fs/cgroup/{name}").read().split()[0])
        except (OSError, ValueError):
            pass
    try:
        for line in open("/sys/fs/cgroup/cpu.stat"):
            key, value = line.split()
            if key == "usage_usec":
                out["cpu_usec"] = int(value)
    except OSError:
        pass
    return out


async def sentinel(port: int, http_port: int, focus_cmd: str | None = None):
    cdp = await Cdp.connect(port)
    target = (await cdp.send("Target.createTarget", {"url": f"http://127.0.0.1:{http_port}/?agent=human",
                                                     "newWindow": True}))["targetId"]
    session = (await cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
    await wait_loaded(cdp, session)
    await cdp.send("Page.bringToFront", {}, session)
    if focus_cmd:
        await asyncio.sleep(0.5)
        proc = await asyncio.create_subprocess_shell(focus_cmd)
        await proc.wait()
    await asyncio.sleep(0.5)
    return cdp, target, session


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))] * 1000, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--agents", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--mode", choices=("control", "free", "focus"), default="free")
    parser.add_argument("--ops", default="all", choices=("all",) + OPS)
    parser.add_argument("--chars", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--op-timeout", type=float, default=30.0)
    parser.add_argument("--no-paint-wait", dest="paint_wait", action="store_false",
                        help="send popup input right after load; Chrome drops input that precedes the first frame")
    parser.add_argument("--sentinel-port", type=int, help="Chrome for the human sentinel window (default --port)")
    parser.add_argument("--sentinel-focus-cmd", help="shell command that gives the sentinel compositor focus")
    args = parser.parse_args()

    http_port = serve()
    loop = asyncio.new_event_loop()
    s_cdp, s_target, s_session = loop.run_until_complete(
        sentinel(args.sentinel_port or args.port, http_port, args.sentinel_focus_cmd))
    blur0 = loop.run_until_complete(s_cdp.evaluate(s_session, "window.__blur"))
    focus0 = loop.run_until_complete(s_cdp.evaluate(s_session, "document.hasFocus()"))

    ctx = mp.get_context("fork")
    barrier, lock, results = ctx.Barrier(args.agents), ctx.Lock(), ctx.Queue()
    before = cgroup()
    t0 = time.monotonic()
    procs = [ctx.Process(target=agent_main, args=(i, args, http_port, barrier, lock, results))
             for i in range(args.agents)]
    for proc in procs:
        proc.start()
    rows = [results.get(timeout=args.rounds * 60 + 300) for _ in procs]
    for proc in procs:
        proc.join(30)
    wall = time.monotonic() - t0
    after = cgroup()

    blur1 = loop.run_until_complete(s_cdp.evaluate(s_session, "window.__blur"))
    focus1 = loop.run_until_complete(s_cdp.evaluate(s_session, "document.hasFocus()"))
    sentinel_log = loop.run_until_complete(s_cdp.evaluate(s_session, "window.__log.length"))
    loop.run_until_complete(s_cdp.send("Target.closeTarget", {"targetId": s_target}))

    all_lat: dict[str, list[float]] = {op: [] for op in OPS}
    for row in rows:
        for op, values in row["lat"].items():
            all_lat[op].extend(values)
    ops = sum(row["ops"] for row in rows)
    failures = sum(row["failure_count"] for row in rows)
    summary = {
        "mode": args.mode, "agents": args.agents, "rounds": args.rounds, "ops": ops,
        "failures": failures, "crosstalk": sum(row["crosstalk"] for row in rows) + sentinel_log,
        "sentinel": {"blur_events": blur1 - blur0, "focused_before": focus0, "focused_after": focus1,
                     "foreign_events": sentinel_log},
        "wall_s": round(wall, 2), "ops_per_s": round(ops / wall, 2),
        "latency_ms": {op: {"p50": pct(v, .5), "p95": pct(v, .95), "n": len(v)} for op, v in all_lat.items() if v},
        "cpu_s": round((after.get("cpu_usec", 0) - before.get("cpu_usec", 0)) / 1e6, 1),
        "mem_peak_mb": round(after.get("memory.peak", 0) / 2 ** 20), "pids_peak": after.get("pids.peak"),
        "sample_failures": [f for row in rows for f in row["failures"]][:12],
    }
    print(json.dumps(summary, indent=1))
    return 0 if failures == 0 and summary["crosstalk"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
