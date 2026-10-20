#!/usr/bin/env python3
"""Login-sharing harness: one identity, N agents, two architectures.

Runs inside a lab agent desktop as user abc, against the synthetic auth server
in auth_server.py (no real credentials).

Candidates:
  ab  one Chrome process for the identity; every agent its own window
      (Target.createTarget newWindow) in the shared profile.
  c   one Chrome process and profile per agent, plus a broker that replicates
      cookies (Storage.getCookies -> Storage.setCookies, partitionKey and flags
      preserved) and localStorage (DOMStorage) between them.

Broker policies (candidate c):
  primary  one-way mirror from agent 0's profile (the authoritative login).
  union    multi-master last-writer-wins; deletions are not propagated.
  lww      multi-master last-writer-wins with tombstones; values the broker has
           seen superseded or deleted are rejected if a replica writes them back.

Scenarios: a login-fanout, b concurrent-refresh, c logout, d crash, e storage
visibility, f expiry. Only Target, Page, Storage, DOMStorage and one-shot
Runtime.evaluate are used; Runtime is never enabled.

  python3 bench_auth.py --candidate ab --agents 4
  python3 bench_auth.py --candidate c --agents 4 --policy lww --interval 0.25
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth_server import AuthState, serve  # noqa: E402
from cdp_ws import Cdp, CdpError  # noqa: E402

RUN_CHROME = "/opt/ghostship-agent-desktop/run-chrome"
PROFILES = "/config/agent-desktop/chrome"
HOSTS = ("127.0.0.1", "localhost")


def now() -> float:
    return time.monotonic()


async def until(pred, timeout: float, step: float = 0.05):
    """Poll an async predicate; return (elapsed, value) or (None, last)."""
    t0, last = now(), None
    while True:
        try:
            last = await pred()
        except (CdpError, asyncio.TimeoutError, OSError) as exc:
            last = exc
        if last and not isinstance(last, Exception):
            return now() - t0, last
        if now() - t0 > timeout:
            return None, last
        await asyncio.sleep(step)


class Browser:
    def __init__(self, name: str, port: int):
        self.name, self.port = name, port
        self.profile = f"{PROFILES}/{name}"
        self.proc: subprocess.Popen | None = None
        self.cdp: Cdp | None = None
        self.up = False

    async def start(self, fresh: bool = False) -> float:
        if fresh:
            shutil.rmtree(self.profile, ignore_errors=True)
        t0 = now()
        log = open(f"/tmp/authlab-{self.name}.log", "ab")
        self.proc = subprocess.Popen([RUN_CHROME, self.name, str(self.port)], stdout=log, stderr=log,
                                     start_new_session=True)

        async def ready():
            return await asyncio.to_thread(lambda: urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/json/version", timeout=1).status == 200)

        el, _ = await until(ready, 30, 0.1)
        if el is None:
            raise RuntimeError(f"{self.name}: DevTools never came up")
        self.cdp = await Cdp.connect(self.port)
        self.up = True
        return now() - t0

    async def kill9(self) -> None:
        self.up = False
        if self.cdp:
            await self.cdp.close()
            self.cdp = None
        os.kill(self.proc.pid, signal.SIGKILL)
        await asyncio.to_thread(self.proc.wait)
        await asyncio.sleep(0.5)

    async def stop(self) -> None:
        self.up = False
        if self.cdp:
            await self.cdp.close()
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(asyncio.to_thread(self.proc.wait), 10)
            except asyncio.TimeoutError:
                os.killpg(self.proc.pid, signal.SIGKILL)

    async def cookies(self) -> list[dict]:
        cs = (await self.cdp.send("Storage.getCookies"))["cookies"]
        return [c for c in cs if c["domain"].lstrip(".") in HOSTS]

    async def set_cookies(self, cookies: list[dict]) -> None:
        if cookies:
            await self.cdp.send("Storage.setCookies", {"cookies": [cookie_param(c) for c in cookies]})

    async def delete_cookies(self, cookies: list[dict]) -> None:
        if cookies:
            await self.cdp.send("Storage.setCookies", {"cookies": [
                {**cookie_param(c), "value": "", "expires": 1} for c in cookies]})

    async def clear_site_data(self, port: int, agent: "Agent") -> None:
        # clearDataForOrigin fails on the browser target; a page session works.
        for h in HOSTS:
            await agent.cdp.send("Storage.clearDataForOrigin", {"origin": f"http://{h}:{port}", "storageTypes": "all"},
                                 agent.session)
        await self.delete_cookies(await self.cookies())


def cookie_key(c: dict) -> tuple:
    return (c["name"], c["domain"], c["path"], json.dumps(c.get("partitionKey"), sort_keys=True))


def cookie_param(c: dict) -> dict:
    p = {k: c[k] for k in ("name", "value", "path", "secure", "httpOnly", "priority", "sourceScheme", "sourcePort")
         if k in c}
    if c.get("sameSite"):
        p["sameSite"] = c["sameSite"]
    if c["domain"].startswith("."):
        p["domain"] = c["domain"]
    else:  # host-only: set by URL so it stays host-only
        p["url"] = f"http://{c['domain']}:{c.get('sourcePort', 80)}{c['path']}"
    if not c.get("session") and c.get("expires", -1) > 0:
        p["expires"] = c["expires"]
    if c.get("partitionKey"):
        p["partitionKey"] = c["partitionKey"]
    return p


class Agent:
    def __init__(self, idx: int, browser: Browser, url: str):
        self.idx, self.browser, self.url = idx, browser, url
        self.cdp: Cdp | None = None
        self.target = self.session = None

    async def open(self) -> None:
        self.cdp = await Cdp.connect(self.browser.port)
        self.target = (await self.cdp.send("Target.createTarget", {"url": "about:blank", "newWindow": True,
                                                                   "background": True}))["targetId"]
        self.session = (await self.cdp.send("Target.attachToTarget", {"targetId": self.target,
                                                                       "flatten": True}))["sessionId"]
        await self.goto(self.url)

    async def goto(self, url: str) -> None:
        await self.cdp.send("Page.navigate", {"url": url}, self.session)
        el, _ = await until(lambda: self.ev("document.readyState === 'complete' && !!window.auth"), 15)
        if el is None:
            raise RuntimeError(f"agent {self.idx}: page did not load")

    async def reload(self) -> None:
        await self.goto(self.url)

    async def ev(self, expr: str, timeout: float = 15):
        return await self.cdp.evaluate(self.session, expr, timeout)

    async def whoami(self) -> dict:
        return await self.ev("auth.whoami()")

    async def close(self) -> None:
        if self.cdp:
            try:
                await self.cdp.close()
            except Exception:
                pass


class Replicator:
    """Generic multi-browser item replication with LWW, tombstones, primary mirror."""

    def __init__(self, broker: "Broker", kind: str):
        self.b, self.kind = broker, kind
        self.canonical: dict = {}
        self.history: dict = {}   # key -> set of superseded/deleted values
        self.known: dict[int, dict] = {}

    def reset(self, i: int | None = None) -> None:
        if i is None:
            self.canonical, self.history, self.known = {}, {}, {}
        else:
            self.known[i] = {}
            self.b.fresh.add(i)

    def tick(self, snaps: dict[int, dict]) -> dict[int, tuple[list, list]]:
        pol, st, t = self.b.policy, self.b.stats, time.time()
        for i in sorted(snaps):
            if pol == "primary" and i != 0:
                continue
            cur, known = snaps[i], self.known.get(i, {})
            fresh = i in self.b.fresh
            for key in set(cur) | set(known):
                old, new = known.get(key), cur.get(key)
                ov, nv = old and old["value"], new and new["value"]
                if ov == nv:
                    continue
                if new is None:
                    if fresh:
                        continue  # a restarted profile missing items is not a logout
                    expired = self.kind == "cookie" and not old.get("session") and old.get("expires", 0) <= t + 1
                    if pol == "union" and not expired:
                        continue
                    canon = self.canonical.get(key)
                    if canon and canon["value"] == ov:
                        self.history.setdefault(key, set()).add(ov)
                        del self.canonical[key]
                        st[f"{self.kind}_tombstones"] += 0 if expired else 1
                    continue
                if pol == "lww" and nv in self.history.get(key, ()):
                    st[f"{self.kind}_stale_rejected"] += 1
                    continue
                canon = self.canonical.get(key)
                if canon is None or canon["value"] != nv:
                    if canon:
                        self.history.setdefault(key, set()).add(canon["value"])
                    self.canonical[key] = new
                    st[f"{self.kind}_adopted"] += 1
        self.b.fresh.difference_update(snaps)
        plan: dict[int, tuple[list, list]] = {}
        for i, cur in snaps.items():
            put = [c for k, c in self.canonical.items() if (cur.get(k) or {}).get("value") != c["value"]]
            drop = [c for k, c in cur.items() if k not in self.canonical and (pol != "union" or k in self.history)]
            plan[i] = (put, drop)
            self.known[i] = dict(self.canonical)
        return plan


class Broker:
    def __init__(self, browsers: list[Browser], agents: list[Agent], policy: str, interval: float, port: int,
                 storage: bool = True):
        self.browsers, self.agents, self.policy, self.interval = browsers, agents, policy, interval
        self.origin = f"http://127.0.0.1:{port}"
        self.storage = storage
        self.fresh: set[int] = set()
        self.stats: dict[str, float] = {k: 0 for k in (
            "ticks", "cookie_adopted", "cookie_tombstones", "cookie_stale_rejected", "cookie_put", "cookie_drop",
            "ls_adopted", "ls_tombstones", "ls_stale_rejected", "ls_put", "ls_drop", "errors")}
        self.tick_ms: list[float] = []
        self.cookies = Replicator(self, "cookie")
        self.ls = Replicator(self, "ls")
        self.paused = False
        self.task: asyncio.Task | None = None

    def reset(self, i: int | None = None) -> None:
        self.cookies.reset(i)
        self.ls.reset(i)

    async def _ls_get(self, i: int) -> dict:
        a = self.agents[i]
        r = await a.cdp.send("DOMStorage.getDOMStorageItems", {"storageId": {
            "securityOrigin": self.origin, "isLocalStorage": True}}, a.session)
        return {k: {"key": k, "value": v} for k, v in r["entries"]}

    async def _ls_apply(self, i: int, put: list, drop: list) -> None:
        a = self.agents[i]
        sid = {"securityOrigin": self.origin, "isLocalStorage": True}
        for it in put:
            await a.cdp.send("DOMStorage.setDOMStorageItem", {"storageId": sid, "key": it["key"],
                                                              "value": it["value"]}, a.session)
        for it in drop:
            await a.cdp.send("DOMStorage.removeDOMStorageItem", {"storageId": sid, "key": it["key"]}, a.session)

    async def tick(self) -> None:
        t0 = now()
        live = [i for i, b in enumerate(self.browsers) if b.up]
        snaps = await asyncio.gather(*(self.browsers[i].cookies() for i in live), return_exceptions=True)
        csnap = {i: {cookie_key(c): c for c in s} for i, s in zip(live, snaps) if not isinstance(s, Exception)}
        for i, (put, drop) in self.cookies.tick(csnap).items():
            await self.browsers[i].set_cookies(put)
            await self.browsers[i].delete_cookies(drop)
            self.stats["cookie_put"] += len(put)
            self.stats["cookie_drop"] += len(drop)
        if self.storage:
            lsn = await asyncio.gather(*(self._ls_get(i) for i in live), return_exceptions=True)
            lsnap = {i: s for i, s in zip(live, lsn) if not isinstance(s, Exception)}
            for i, (put, drop) in self.ls.tick(lsnap).items():
                await self._ls_apply(i, put, drop)
                self.stats["ls_put"] += len(put)
                self.stats["ls_drop"] += len(drop)
        self.stats["ticks"] += 1
        self.tick_ms.append((now() - t0) * 1000)

    async def run(self) -> None:
        while True:
            if not self.paused:
                try:
                    await self.tick()
                except Exception as exc:  # a browser mid-crash; keep going
                    self.stats["errors"] += 1
                    self.last_error = repr(exc)
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        self.task = asyncio.ensure_future(self.run())

    async def quiesce(self, ticks: int = 3) -> None:
        target = self.stats["ticks"] + ticks
        while self.stats["ticks"] < target:
            await asyncio.sleep(self.interval / 2)


class Lab:
    def __init__(self, args):
        self.a = args
        self.state = AuthState(args.session_mode, args.access_ttl, args.reuse_grace)
        self.port = serve(self.state, args.server_port)
        self.url = lambda i: f"http://127.0.0.1:{self.port}/app?agent={i}&client={args.client}"
        n = args.agents
        if args.candidate == "ab":
            b = Browser(f"authlab-ab", args.base_port)
            self.browsers = [b]
            self.agents = [Agent(i, b, self.url(i)) for i in range(n)]
        else:
            self.browsers = [Browser(f"authlab-c{i}", args.base_port + i) for i in range(n)]
            self.agents = [Agent(i, self.browsers[i], self.url(i)) for i in range(n)]
        self.broker: Broker | None = None

    async def setup(self) -> dict:
        boots = await asyncio.gather(*(b.start(fresh=True) for b in self.browsers))
        for ag in self.agents:
            await ag.open()
        if self.a.candidate == "c":
            self.broker = Broker(self.browsers, self.agents, self.a.policy, self.a.interval, self.port,
                                 storage=not self.a.no_storage)
            self.broker.start()
        return {"chrome_start_s": [round(x, 2) for x in boots]}

    async def settle(self, extra: float = 0.3) -> None:
        if self.broker:
            await self.broker.quiesce(3)
        await asyncio.sleep(extra)

    async def reset(self) -> None:
        """Logged-out, storage-empty baseline in every profile."""
        if self.broker:
            self.broker.paused = True
            await asyncio.sleep(self.a.interval + 0.2)
        for b in self.browsers:
            await b.clear_site_data(self.port, next(ag for ag in self.agents if ag.browser is b))
        for ag in self.agents:
            await ag.reload()
        if self.broker:
            self.broker.reset()
            self.broker.paused = False
        await self.settle()

    async def login(self) -> float | None:
        await self.agents[0].ev("auth.login()")
        el, _ = await until(self.all_signed_in, 15)
        return el

    async def all_signed_in(self) -> bool:
        ws = await asyncio.gather(*(ag.whoami() for ag in self.agents))
        return all(w["session"] and w["access"] for w in ws)

    async def jars(self) -> list[list[dict]]:
        return [await b.cookies() if b.up else [] for b in self.browsers]

    async def restart(self, i: int) -> tuple[float, list[dict]]:
        b = self.browsers[i]
        t = await b.start()
        jar = await b.cookies()  # what the profile recovered from disk
        if self.broker:
            self.broker.reset(i)
            if not self.a.no_restart_sync:
                # Converge the restarted profile before any page can use its stale jar.
                self.broker.paused = True
                await self.broker.tick()
                self.broker.paused = False
        for ag in self.agents:
            if ag.browser is b:
                await ag.close()
                await ag.open()
        return t, jar

    # ---------------------------------------------------------------- scenarios
    async def s_a(self) -> dict:
        await self.reset()
        el = await self.login()
        per = []
        for ag in self.agents:
            w = await ag.whoami()
            per.append(bool(w["session"] and w["access"]))
        return {"pass": el is not None and all(per), "all_signed_in_s": el and round(el, 3), "signed_in": per}

    async def s_b(self) -> dict:
        await self.reset()
        if await self.login() is None:
            return {"pass": False, "error": "login did not fan out"}
        base = self.state.snapshot()["counts"]
        failed_round, outcomes = None, {"refreshed": 0, "skipped": 0, "error": 0}
        lat = []
        for r in range(self.a.rounds):
            self.state.expire_access()
            barrier = asyncio.Barrier(len(self.agents))

            async def go(ag):
                await barrier.wait()
                t0 = now()
                res = await ag.ev("auth.ensure()")
                lat.append(now() - t0)
                return res
            res = await asyncio.gather(*(go(ag) for ag in self.agents))
            for x in res:
                outcomes["skipped" if x.get("skipped") else "error" if x.get("error") else "refreshed"] += 1
            if any(x.get("error") for x in res) and failed_round is None:
                failed_round = r
                break
            await asyncio.sleep(self.a.gap)
        await self.settle()
        final = await asyncio.gather(*(ag.ev("auth.ensure().then(() => auth.whoami())") for ag in self.agents))
        snap = self.state.snapshot()
        counts = {k: snap["counts"][k] - base.get(k, 0) for k in snap["counts"]}
        revoked = [f for f in snap["families"].values() if f["revoked"] and f["why"] == "refresh_reuse"]
        signed = [bool(w["session"] and w["access"]) for w in final]
        return {"pass": all(signed) and not revoked and failed_round is None, "rounds": self.a.rounds,
                "failed_round": failed_round, "outcomes": outcomes, "server": counts,
                "families_revoked_by_reuse": len(revoked), "signed_in_end": signed,
                "refresh_p50_ms": round(sorted(lat)[len(lat) // 2] * 1000, 1) if lat else None}

    async def s_c(self) -> dict:
        await self.reset()
        if await self.login() is None:
            return {"pass": False, "error": "login did not fan out"}
        await self.settle()
        k = len(self.agents) - 1
        pre = await self.browsers[0].cookies()
        await self.agents[k].ev("auth.logout()")

        async def all_out():
            ws = await asyncio.gather(*(ag.whoami() for ag in self.agents))
            return not any(w["session"] for w in ws)

        async def jars_clear():
            return not any(c["name"] == "sid" for jar in await self.jars() for c in jar)
        t_out, _ = await until(all_out, self.a.logout_t)
        t_jar, _ = await until(jars_clear, 10)
        await asyncio.sleep(max(2.0, 6 * self.a.interval))
        ws = await asyncio.gather(*(ag.whoami() for ag in self.agents))
        sid_back = sum(any(c["name"] == "sid" for c in jar) for jar in await self.jars())
        natural = {"session_valid_agents": sum(bool(w["session"]) for w in ws), "jars_with_sid": sid_back}
        out = {"logout_agent": k, "all_signed_out_s": t_out and round(t_out, 3),
               "jars_clear_s": t_jar and round(t_jar, 3), "after_settle": natural}
        ok = t_out is not None and t_jar is not None and not natural["session_valid_agents"] and not sid_back
        if self.a.candidate == "c":
            # A stale replica (e.g. restored from disk) writes the pre-logout jar back into agent 0's profile.
            await self.browsers[0].set_cookies(pre)
            await asyncio.sleep(max(2.0, 6 * self.a.interval))
            ws = await asyncio.gather(*(ag.whoami() for ag in self.agents))
            jars = await self.jars()
            inj = {"session_valid_agents": sum(bool(w["session"]) for w in ws),
                   "jars_with_old_sid": sum(any(c["name"] == "sid" and c["value"] in {p["value"] for p in pre}
                                                for c in jar) for jar in jars)}
            out["stale_writeback"] = inj
            ok = ok and not inj["session_valid_agents"] and inj["jars_with_old_sid"] <= 1
        out["pass"] = ok
        return out

    async def s_d(self) -> dict:
        out = {}
        for label, logout_first in (("persist", False), ("logout_then_crash", True)):
            await self.reset()
            if await self.login() is None:
                return {"pass": False, "error": "login did not fan out"}
            mark = f"D{int(time.time())}"
            await self.agents[0].ev(f"auth.mark({json.dumps(mark)})")
            await self.settle()
            await asyncio.sleep(self.a.crash_after)
            if logout_first:  # logged-in state is on disk; the logout is not yet
                await self.agents[0].ev("auth.logout()")
                await asyncio.sleep(1.0)
            if self.broker:
                self.broker.paused = True
            await self.browsers[0].kill9()
            if self.broker:
                self.broker.paused = False
            # C: other agents keep running while agent 0's browser is down; one of
            # them rotates the refresh token, so agent 0's on-disk token goes stale.
            await asyncio.sleep(1.0)
            rotated = False
            if len(self.browsers) > 1 and not logout_first:
                self.state.expire_access()
                rotated = "error" not in await self.agents[1].ev("auth.ensure()")
                await asyncio.sleep(0.5)
            t_restart, jar0 = await self.restart(0)
            a0 = self.agents[0]
            # The agent resumes work immediately, as a real one would.
            w = await a0.ev("auth.ensure().then(() => auth.whoami())")
            m = await a0.ev("auth.markers()")
            await self.settle()
            ws = await asyncio.gather(*(ag.whoami() for ag in self.agents))
            r = {"restart_s": round(t_restart, 2), "jar_on_disk": sorted(c["name"] for c in jar0),
                 "rotated_while_down": rotated,
                 "signed_in": bool(w["session"] and w["access"]), "session_cookie_valid": bool(w["session"]),
                 "ls": m["ls"] == mark, "idb": m["idb"] == mark, "ss_cleared": m["ss"] is None,
                 "session_valid_agents": sum(bool(x["session"]) for x in ws)}
            if logout_first:
                r["pass"] = r["session_valid_agents"] == 0
            else:
                r["pass"] = (r["signed_in"] and r["ls"] and r["idb"] and r["ss_cleared"]
                             and r["session_valid_agents"] == len(self.agents))
            out[label] = r
        out["pass"] = all(v["pass"] for v in out.values() if isinstance(v, dict))
        return out

    async def s_e(self) -> dict:
        await self.reset()
        if await self.login() is None:
            return {"pass": False, "error": "login did not fan out"}
        a0 = self.agents[0]
        await a0.reload()
        await until(lambda: a0.ev("!!window.__embed"), 5)
        mark = f"E{int(time.time())}"
        await a0.ev(f"auth.mark({json.dumps(mark)})")
        await self.settle()
        for ag in self.agents[1:]:
            await ag.reload()
            await until(lambda: ag.ev("!!window.__embed"), 5)
        await self.settle()
        pc0 = next((c for c in await self.browsers[0].cookies() if c["name"] == "pc"), None)
        per = []
        for ag in self.agents:
            m = await ag.ev("auth.markers()")
            pc = next((c for c in await ag.browser.cookies() if c["name"] == "pc"), None)
            per.append({"agent": ag.idx, "ls": m["ls"] == mark, "idb": m["idb"] == mark,
                        "ss": m["ss"] == mark, "pc_same": bool(pc and pc0 and pc["value"] == pc0["value"]),
                        "pc_partition": pc and pc.get("partitionKey"),
                        "iframe_sees_pc": bool(m["embed"] and pc0 and m["embed"].get("pc") == pc0["value"]),
                        "ui_doc_cookie": "ui=" in (m["docCookie"] or "")})
        # Partitioning sanity: top-level localhost must not see the 127.0.0.1-partitioned cookie.
        tgt = (await a0.cdp.send("Target.createTarget", {"url": f"http://localhost:{self.port}/embed/state",
                                                         "background": True}))["targetId"]
        s = (await a0.cdp.send("Target.attachToTarget", {"targetId": tgt, "flatten": True}))["sessionId"]
        _, body = await until(lambda: a0.cdp.evaluate(s, "document.readyState === 'complete' && document.body.innerText"), 5)
        await a0.cdp.send("Target.closeTarget", {"targetId": tgt})
        toplevel_pc = json.loads(body).get("pc") if isinstance(body, str) else "error"
        ok = (all(p["ls"] and p["idb"] and p["pc_same"] and p["iframe_sees_pc"] and p["ui_doc_cookie"] for p in per)
              and per[0]["ss"] and not any(p["ss"] for p in per[1:]) and toplevel_pc is None
              and bool(pc0 and pc0.get("partitionKey")))
        return {"pass": ok, "per_agent": per, "pc_partition_key": pc0 and pc0.get("partitionKey"),
                "pc_visible_top_level_localhost": toplevel_pc}

    async def s_f(self) -> dict:
        await self.reset()
        if await self.login() is None:
            return {"pass": False, "error": "login did not fan out"}
        await self.settle()
        jars = await self.jars()
        ref = {c["name"]: c for c in jars[0]}
        mism = []
        for i, jar in enumerate(jars[1:], 1):
            for c in jar:
                r = ref.get(c["name"])
                if not r:
                    mism.append((i, c["name"], "missing-in-0"))
                    continue
                for f in ("value", "httpOnly", "secure", "sameSite", "session", "path", "domain"):
                    if c.get(f) != r.get(f):
                        mism.append((i, c["name"], f))
                if abs(c.get("expires", 0) - r.get("expires", 0)) > 2:
                    mism.append((i, c["name"], "expires"))
                if c.get("partitionKey") != r.get("partitionKey"):
                    mism.append((i, c["name"], "partitionKey"))
            for name in set(ref) - {c["name"] for c in jar}:
                mism.append((i, name, "missing"))
        await asyncio.sleep(self.a.access_ttl + 1.5)
        jars = await self.jars()
        at_left = sum(any(c["name"] == "at" for c in jar) for jar in jars)
        ws = await asyncio.gather(*(ag.whoami() for ag in self.agents))
        access_valid = sum(bool(w["access"]) for w in ws)
        await self.agents[0].ev("auth.ensure()")

        async def all_access():
            return all(w["access"] for w in await asyncio.gather(*(ag.whoami() for ag in self.agents)))
        t_prop, _ = await until(all_access, 10)
        ok = not mism and at_left == 0 and access_valid == 0 and t_prop is not None
        return {"pass": ok, "attr_mismatches": mism[:12], "jars_with_expired_at": at_left,
                "access_valid_after_expiry": access_valid, "refresh_visible_all_s": t_prop and round(t_prop, 3)}

    async def close(self) -> None:
        if self.broker and self.broker.task:
            self.broker.task.cancel()
        for ag in self.agents:
            await ag.close()
        for b in self.browsers:
            await b.stop()
            if not self.a.keep:
                shutil.rmtree(b.profile, ignore_errors=True)


async def main(args) -> dict:
    lab = Lab(args)
    out = {"config": {k: v for k, v in vars(args).items() if k not in ("json",)}, "port": lab.port}
    try:
        out["setup"] = await lab.setup()
        print(json.dumps({"ready": out["setup"]}), flush=True)
        for s in filter(None, args.scenarios.split(",")):
            t0 = now()
            try:
                out[s] = await getattr(lab, f"s_{s}")()
            except Exception as exc:
                out[s] = {"pass": False, "error": repr(exc)}
            out[s]["wall_s"] = round(now() - t0, 1)
            print(json.dumps({s: out[s]}), flush=True)
        if lab.broker:
            ms = sorted(lab.broker.tick_ms)
            out["broker"] = {**lab.broker.stats, "tick_p50_ms": round(ms[len(ms) // 2], 1),
                             "tick_p95_ms": round(ms[int(len(ms) * .95)], 1),
                             "last_error": getattr(lab.broker, "last_error", None)}
        out["server"] = lab.state.snapshot()["counts"]
        if args.hold:  # keep browsers up for external measurement (podman stats)
            await asyncio.sleep(args.hold)
    finally:
        await lab.close()
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--candidate", choices=("ab", "c"), required=True)
    p.add_argument("--agents", type=int, default=4)
    p.add_argument("--policy", choices=("primary", "union", "lww"), default="lww")
    p.add_argument("--interval", type=float, default=0.25, help="broker poll interval (s)")
    p.add_argument("--no-storage", action="store_true", help="broker replicates cookies only")
    p.add_argument("--no-restart-sync", action="store_true",
                   help="do not converge a restarted profile before reopening its pages")
    p.add_argument("--session-mode", choices=("server", "stateless"), default="server")
    p.add_argument("--client", choices=("lock", "naive"), default="lock")
    p.add_argument("--reuse-grace", type=float, default=0.0)
    p.add_argument("--access-ttl", type=float, default=5.0)
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--gap", type=float, default=0.5, help="pause between refresh rounds (s)")
    p.add_argument("--logout-t", type=float, default=5.0)
    p.add_argument("--crash-after", type=float, default=3.0, help="seconds between login and kill -9")
    p.add_argument("--scenarios", default="a,b,c,d,e,f")
    p.add_argument("--base-port", type=int, default=9240)
    p.add_argument("--server-port", type=int, default=0)
    p.add_argument("--keep", action="store_true", help="keep lab profiles")
    p.add_argument("--hold", type=float, default=0, help="keep browsers up this long after the scenarios")
    p.add_argument("--json", help="write the full result here")
    a = p.parse_args()
    result = asyncio.run(main(a))
    summary = {s: result[s]["pass"] for s in filter(None, a.scenarios.split(","))}
    print(json.dumps({"summary": summary, "broker": result.get("broker"), "server": result.get("server")}))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(result, fh, indent=1, default=str)
