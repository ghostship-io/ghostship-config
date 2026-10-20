"""Synthetic authentication server for the desktop login-sharing harness.

One threaded HTTP listener serves two sites: http://127.0.0.1:<port> (the app)
and http://localhost:<port> (a third party embedded in an iframe). Chrome
treats both as secure contexts, so Secure and Partitioned cookies work over
plain HTTP. No real credentials exist anywhere: the user is "synthetic".

Cookies issued by /login (all Path=/ unless noted):
  sid  session        HttpOnly Secure SameSite=Lax  Max-Age=3600
  at   access token   HttpOnly Secure SameSite=Lax  Max-Age=ACCESS_TTL
  rt   refresh token  HttpOnly Secure SameSite=Lax  Path=/auth  Max-Age=3600, rotating
  st   strict marker  HttpOnly Secure SameSite=Strict
  ui   UI hint        Secure SameSite=Lax (readable by page JS)
and the embedded http://localhost iframe sets
  pc   partitioned    Secure SameSite=None Partitioned

Refresh-token rotation follows OAuth reuse detection: each /auth/refresh with
the current token issues a new one; presenting any superseded token revokes
the whole family and its session. --reuse-grace S tolerates the immediately
previous token for S seconds (Auth0 "reuse interval" / Okta grace period).

Session modes:
  server     sid is an opaque handle; logout tombstones it server-side.
  stateless  sid is a signed token valid until its expiry; logout only clears
             cookies and revokes the refresh family (JWT-style sites).
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import os
import secrets
import socketserver
import threading
import time
import urllib.parse

APP_PAGE = r"""<!doctype html><html><head><title>auth-lab</title></head>
<body style="font:14px sans-serif"><h3>auth lab</h3>
<iframe id=emb src="http://localhost:__PORT__/embed" style="width:600px;height:80px"></iframe>
<script>
const Q = new URLSearchParams(location.search);
const AGENT = Q.get('agent') || '?';
const LOCKED = Q.get('client') !== 'naive';
document.title = 'auth-' + AGENT;
window.__embed = null;
addEventListener('message', e => { if (e.origin === 'http://localhost:__PORT__') window.__embed = e.data; });
function idb() {
  return new Promise((ok, bad) => {
    const r = indexedDB.open('authlab', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('kv');
    r.onsuccess = () => ok(r.result); r.onerror = () => bad(r.error);
  });
}
async function idbPut(k, v) { const db = await idb(); return new Promise(ok => { const t = db.transaction('kv', 'readwrite'); t.objectStore('kv').put(v, k); t.oncomplete = () => { db.close(); ok(true); }; }); }
async function idbGet(k) { const db = await idb(); return new Promise(ok => { const r = db.transaction('kv').objectStore('kv').get(k); r.onsuccess = () => { db.close(); ok(r.result ?? null); }; }); }
async function j(path, opts) { const r = await fetch(path, Object.assign({credentials: 'include', cache: 'no-store'}, opts || {})); return Object.assign({http: r.status}, await r.json()); }
async function refreshInner() {
  const w = await j('/whoami');
  if (!w.session) return {skipped: 'no-session', w};
  if (w.access) return {skipped: 'fresh'};
  return await j('/auth/refresh', {method: 'POST'});
}
window.auth = {
  whoami: () => j('/whoami'),
  login: () => j('/login', {method: 'POST'}),
  logout: () => j('/logout', {method: 'POST'}),
  // Refresh as a multi-tab-aware SPA would: under a Web Lock, re-check and
  // skip when another tab already refreshed. 'naive' clients skip the lock.
  ensure: async () => LOCKED ? navigator.locks.request('authlab-refresh', refreshInner) : refreshInner(),
  mark: async v => { localStorage.setItem('lsMark', v); sessionStorage.setItem('ssMark', v); await idbPut('mark', v); return true; },
  markers: async () => ({ls: localStorage.getItem('lsMark'), ss: sessionStorage.getItem('ssMark'), idb: await idbGet('mark'), docCookie: document.cookie, embed: window.__embed}),
};
</script></body></html>"""

EMBED_PAGE = r"""<!doctype html><html><body>embed <span id=s></span><script>
fetch('/embed/state', {credentials: 'include', cache: 'no-store'}).then(r => r.json()).then(d => {
  s.textContent = JSON.stringify(d); parent.postMessage(d, '*');
});
</script></body></html>"""


class AuthState:
    def __init__(self, mode: str = "server", access_ttl: float = 5.0, reuse_grace: float = 0.0):
        self.mode, self.access_ttl, self.reuse_grace = mode, access_ttl, reuse_grace
        self.key = secrets.token_bytes(32)
        self.lock = threading.Lock()
        self.sessions: dict[str, dict] = {}   # sid -> {fid, alive}
        self.families: dict[str, dict] = {}   # fid -> {cur, prev, rotated, gen, revoked, why, seen}
        self.access: dict[str, dict] = {}     # at -> {fid, exp}
        self.events: list[dict] = []
        self.counts = {"login": 0, "refresh_ok": 0, "refresh_grace": 0, "refresh_reuse": 0,
                       "refresh_unknown": 0, "logout": 0}

    def log(self, kind: str, **kw) -> None:
        self.events.append({"t": time.time(), "kind": kind, **kw})

    # --- stateless signed session tokens
    def _sign(self, body: str) -> str:
        return body + "." + hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()[:32]

    def _verify(self, tok: str) -> dict | None:
        body, _, mac = tok.rpartition(".")
        if not body or not hmac.compare_digest(self._sign(body), tok):
            return None
        fid, exp = body.split(":")
        return {"fid": fid, "exp": float(exp)} if float(exp) > time.time() else None

    def session_of(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        if self.mode == "stateless":
            return self._verify(sid)
        s = self.sessions.get(sid)
        return s if s and s["alive"] else None

    def login(self) -> dict[str, str]:
        with self.lock:
            fid = secrets.token_hex(6)
            rt = "rt-" + secrets.token_hex(12)
            self.families[fid] = {"cur": rt, "prev": None, "rotated": 0.0, "gen": 0, "revoked": False,
                                  "why": None, "seen": {rt}}
            sid = (self._sign(f"{fid}:{time.time() + 3600:.0f}") if self.mode == "stateless"
                   else "sid-" + secrets.token_hex(12))
            if self.mode == "server":
                self.sessions[sid] = {"fid": fid, "alive": True}
            at = self._new_access(fid)
            self.counts["login"] += 1
            self.log("login", fid=fid)
            return {"sid": sid, "at": at, "rt": rt, "fid": fid}

    def _new_access(self, fid: str) -> str:
        at = "at-" + secrets.token_hex(8)
        self.access[at] = {"fid": fid, "exp": time.time() + self.access_ttl}
        return at

    def _revoke(self, fid: str, why: str) -> None:
        fam = self.families[fid]
        if not fam["revoked"]:
            fam["revoked"], fam["why"] = True, why
            self.log("revoke", fid=fid, why=why)
        for s in self.sessions.values():
            if s["fid"] == fid:
                s["alive"] = False

    def refresh(self, rt: str | None) -> tuple[int, dict]:
        with self.lock:
            fam = next((f for f in self.families.values() if rt and rt in f["seen"]), None)
            if fam is None:
                self.counts["refresh_unknown"] += 1
                return 401, {"error": "unknown_refresh"}
            fid = next(k for k, v in self.families.items() if v is fam)
            if fam["revoked"]:
                self.counts["refresh_unknown"] += 1
                return 401, {"error": "family_revoked", "why": fam["why"]}
            now = time.time()
            if rt == fam["cur"]:
                new = "rt-" + secrets.token_hex(12)
                fam["prev"], fam["cur"], fam["rotated"] = rt, new, now
                fam["gen"] += 1
                fam["seen"].add(new)
                self.counts["refresh_ok"] += 1
                return 200, {"rt": new, "at": self._new_access(fid), "gen": fam["gen"]}
            if rt == fam["prev"] and now - fam["rotated"] <= self.reuse_grace:
                self.counts["refresh_grace"] += 1
                return 200, {"rt": fam["cur"], "at": self._new_access(fid), "gen": fam["gen"], "grace": True}
            self.counts["refresh_reuse"] += 1
            self._revoke(fid, "refresh_reuse")
            return 401, {"error": "refresh_reuse_detected"}

    def logout(self, sid: str | None, rt: str | None) -> None:
        with self.lock:
            self.counts["logout"] += 1
            s = self.session_of(sid)
            fid = s["fid"] if s else next((k for k, f in self.families.items() if rt and rt in f["seen"]), None)
            if fid:
                self._revoke(fid, "logout")
            if self.mode == "server" and sid in self.sessions:
                self.sessions[sid]["alive"] = False
            self.log("logout", fid=fid)

    def whoami(self, cookies: dict[str, str]) -> dict:
        with self.lock:
            s = self.session_of(cookies.get("sid"))
            a = self.access.get(cookies.get("at") or "")
            fam = self.families.get(s["fid"]) if s else None
            access_ok = bool(a and a["exp"] > time.time() and s and a["fid"] == s["fid"]
                             and not self.families[a["fid"]]["revoked"])
            return {"session": bool(s), "access": access_ok, "fid": s["fid"] if s else None,
                    "family_revoked": bool(fam and fam["revoked"]),
                    "has": sorted(k for k in ("sid", "at", "rt", "st", "ui") if k in cookies)}

    def expire_access(self) -> None:
        with self.lock:
            for a in self.access.values():
                a["exp"] = 0.0

    def snapshot(self) -> dict:
        with self.lock:
            return {"counts": dict(self.counts),
                    "families": {k: {"gen": f["gen"], "revoked": f["revoked"], "why": f["why"]}
                                 for k, f in self.families.items()}}


def _cookie(name: str, value: str, *, max_age: float, path: str = "/", http_only: bool = True,
            same_site: str = "Lax", partitioned: bool = False) -> str:
    parts = [f"{name}={value}", f"Path={path}", f"Max-Age={int(max_age)}", "Secure", f"SameSite={same_site}"]
    if http_only:
        parts.append("HttpOnly")
    if partitioned:
        parts.append("Partitioned")
    return "; ".join(parts)


def make_handler(state: AuthState, port: int):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def _cookies(self) -> dict[str, str]:
            out: dict[str, str] = {}
            for part in (self.headers.get("Cookie") or "").split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    out[k] = v
            return out

        def _send(self, code: int, body, ctype: str = "application/json", cookies: list[str] = ()):
            data = (json.dumps(body) if ctype == "application/json" else body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for c in cookies:
                self.send_header("Set-Cookie", c)
            self.end_headers()
            self.wfile.write(data)

        def _host(self) -> str:
            return (self.headers.get("Host") or "").split(":")[0]

        def _issue(self, at: str, rt: str) -> list[str]:
            return [_cookie("at", at, max_age=state.access_ttl), _cookie("rt", rt, max_age=3600, path="/auth")]

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            host = self._host()
            if path == "/app" and host == "127.0.0.1":
                return self._send(200, APP_PAGE.replace("__PORT__", str(port)), "text/html")
            if path == "/embed" and host == "localhost":
                pc = self._cookies().get("pc")
                cookies = [] if pc else [_cookie("pc", "pc-" + secrets.token_hex(6), max_age=3600, http_only=False,
                                                  same_site="None", partitioned=True)]
                return self._send(200, EMBED_PAGE, "text/html", cookies)
            if path == "/embed/state" and host == "localhost":
                return self._send(200, {"pc": self._cookies().get("pc")})
            if path == "/whoami":
                return self._send(200, state.whoami(self._cookies()))
            if path == "/admin/state":
                return self._send(200, state.snapshot())
            self._send(404, {"error": "not_found"})

        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            path = urllib.parse.urlsplit(self.path).path
            c = self._cookies()
            if path == "/login":
                t = state.login()
                return self._send(200, {"ok": True, "fid": t["fid"]}, cookies=[
                    _cookie("sid", t["sid"], max_age=3600), *self._issue(t["at"], t["rt"]),
                    _cookie("st", "strict-" + t["fid"], max_age=3600, same_site="Strict"),
                    _cookie("ui", "ui-" + t["fid"], max_age=3600, http_only=False)])
            if path == "/auth/refresh":
                code, body = state.refresh(c.get("rt"))
                cookies = self._issue(body["at"], body["rt"]) if code == 200 else []
                return self._send(code, {k: v for k, v in body.items() if k not in ("at", "rt")}, cookies=cookies)
            if path == "/logout":
                state.logout(c.get("sid"), c.get("rt"))
                clear = [_cookie(k, "", max_age=0) for k in ("sid", "at", "st", "ui")]
                clear.append(_cookie("rt", "", max_age=0, path="/auth"))
                return self._send(200, {"ok": True}, cookies=clear)
            if path == "/admin/expire-access":
                state.expire_access()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not_found"})

    return Handler


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(state: AuthState, port: int = 0, bind: str = "127.0.0.1") -> int:
    srv = _Server((bind, port), None)  # type: ignore[arg-type]
    real = srv.server_address[1]
    srv.RequestHandlerClass = make_handler(state, real)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return real


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9299)
    p.add_argument("--mode", default="server", choices=("server", "stateless"))
    p.add_argument("--reuse-grace", type=float, default=0.0)
    a = p.parse_args()
    print(serve(AuthState(a.mode, reuse_grace=a.reuse_grace), a.port), flush=True)
    while True:
        time.sleep(3600)
    os._exit(0)
