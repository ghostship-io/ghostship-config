#!/usr/bin/env python3
"""Public bot-detection test pages through Bladebro, one load each.

These pages exist to grade browsers; they are not shops, so testing never
puts a retailer account or the egress address at risk. Each page is loaded
once per Chrome in its own window through Bladebro (the agents' driver) and
its verdict is read from the rendered page. A candidate passes when every
page reports a human, non-headless browser.

  python3 bench_botcheck.py --port 9222 [--out /tmp/botcheck]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_bladebro import Mcp  # noqa: E402
from cdp_ws import Cdp  # noqa: E402

# name: (url, seconds to let the page finish its checks, verdict JS -> JSON)
PAGES = {
    "deviceandbrowserinfo": ("https://deviceandbrowserinfo.com/are_you_a_bot", 12, r"""JSON.stringify((() => {
        const t = document.body.innerText.toLowerCase();
        return {human: t.includes('you are human'), bot: /you are a bot|bot detected/.test(t)};
    })())"""),
    "sannysoft": ("https://bot.sannysoft.com/", 10, r"""JSON.stringify((() => {
        const failed = [...document.querySelectorAll('td.failed, td.result.failed')].map(td =>
          (td.closest('tr') && td.closest('tr').cells[0] ? td.closest('tr').cells[0].innerText : td.innerText).trim());
        const passed = document.querySelectorAll('td.passed').length;
        return {human: failed.length === 0 && passed > 5, failed: failed.slice(0, 10), passed};
    })())"""),
    "creepjs": ("https://abrahamjuliot.github.io/creepjs/", 25, r"""JSON.stringify((() => {
        const t = document.body.innerText;
        const pct = re => { const m = t.match(re); return m ? Number(m[1]) : null; };
        const headless = pct(/(\d+)%\s*headless/i), like = pct(/(\d+)%\s*like headless/i), stealth = pct(/(\d+)%\s*stealth/i);
        return {human: headless === 0 && stealth === 0, headless, likeHeadless: like, stealth};
    })())"""),
}


class Shooter:
    """Step screenshots over a separate Page-domain-only DevTools session."""

    def __init__(self, port: int):
        self.loop = asyncio.new_event_loop()
        self.cdp = self.loop.run_until_complete(Cdp.connect(port))

    def window(self, url: str) -> tuple[str, str]:
        target = self.loop.run_until_complete(
            self.cdp.send("Target.createTarget", {"url": url, "newWindow": True, "background": True}))["targetId"]
        session = self.loop.run_until_complete(
            self.cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        return target, session

    def shot(self, session: str, path: pathlib.Path) -> None:
        try:
            data = self.loop.run_until_complete(self.cdp.send(
                "Page.captureScreenshot", {"format": "jpeg", "quality": 55}, session, timeout=20))["data"]
            path.write_bytes(base64.b64decode(data))
        except Exception:  # evidence only
            pass

    def close(self, target: str) -> None:
        try:
            self.loop.run_until_complete(self.cdp.send("Target.closeTarget", {"targetId": target}))
        except Exception:
            pass


def parse_object(text: str) -> dict:
    """The first JSON object in Bladebro's eval output (raw or string-encoded)."""
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no result in: {text[:120]}")
    if text[start - 1:start] == '"':  # a JSON string holding the object
        value, _ = json.JSONDecoder().raw_decode(text, start - 1)
        return json.loads(value)
    value, _ = json.JSONDecoder().raw_decode(text, start)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--out", default="/tmp/botcheck")
    parser.add_argument("--pages", default=",".join(PAGES))
    parser.add_argument("--bladebro", default="/usr/local/bin/bladebro")
    parser.add_argument("--blade-home", default="/tmp/bench-bladebro-home")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, BLADE_LANE="real", BLADE_NO_UPDATE_CHECK="1", HOME="/config", BLADE_HOME=args.blade_home)
    results = {}
    shooter = Shooter(args.port)
    for name in [n for n in args.pages.split(",") if n]:
        url, settle, verdict = PAGES[name]
        target, session = shooter.window("about:blank")
        mcp = Mcp([args.bladebro, "mcp", "--port", str(args.port)], env)
        try:
            mcp.tool("state", op="switch-tab", target_id=target)
            mcp.tool("act", action="navigate", url=url, slim=True)
            time.sleep(settle)
            text = mcp.tool("act", action="eval", js=verdict, slim=True)
            results[name] = parse_object(text)
        except Exception as exc:  # recorded as a failed verdict
            results[name] = {"human": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        finally:
            shooter.shot(session, out / f"{name}.jpg")
            mcp.close()
            shooter.close(target)
    report = {"port": args.port, "pass": all(r.get("human") for r in results.values()), "pages": results}
    (out / "summary.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
