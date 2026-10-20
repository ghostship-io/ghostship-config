#!/usr/bin/env python3
"""Operator viewer for concurrent agent browser windows (stdlib only).

Serves a mobile-first UI under /agents/ on 127.0.0.1:7090 (behind the
container's nginx and Cloudflare Access). Each identity's Chrome is reached
over its loopback DevTools port; a run is the Chrome window whose home tab
is an ``about:blank#ghostship-window-<marker>.<expires>`` anchor, plus the
tabs in that window and the popups its pages open. Every other window stays
invisible.

The viewer only uses Target.*, Browser.getWindowForTarget, Page.* (enable,
screencast, navigation, dialogs) and Input.*. It never enables the Runtime
domain; the single Runtime.evaluate it sends goes to a freshly created
about:blank anchor (a human-owned run) to open that window's first tab.

Pause protocol (shared with the desktop input gate) lives in the runs dir:
``<marker>.pause`` plus ``paused/<targetId>`` for every page of the run.
The agent side marks ``busy/<targetId>`` before it checks ``paused/``; the
viewer writes the pause files first and only then waits for every member's
busy file to clear (or go stale) before any human input reaches the page.

Every request must carry a valid Cloudflare Access JWT (verified here with
the team's published RS256 keys), on top of the same-origin checks.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
from cdp_ws import Cdp, CdpError

BIND = "127.0.0.1"
PORT = int(os.environ.get("VIEWER_PORT", "7090"))
RUNS_DIR = os.environ.get("VIEWER_RUNS_DIR", "/config/agent-desktop/runs")
CDP_PORTS_SPEC = os.environ.get("VIEWER_CDP_PORTS", "agent=9222,personal=9223")
IDENTITIES = ("agent", "personal")

RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
TARGET_ID_RE = re.compile(r"[A-Za-z0-9]{1,64}")
ANCHOR_RE = re.compile(r"about:blank#ghostship-window-([A-Za-z0-9_-]{1,64})(?:\.(\d{1,12}))?")

STATIC = {"": ("index.html", "text/html; charset=utf-8"),
          "index.html": ("index.html", "text/html; charset=utf-8"),
          "app.js": ("app.js", "text/javascript; charset=utf-8"),
          "app.css": ("app.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

LIVE_FPS = 12.0
LIVE_QUALITY = 65
MAX_CAST_EDGE = 1920
THUMB_SIZE = (480, 300)
THUMB_QUALITY = 45
THUMB_INTERVAL = 2.0
THUMB_IDLE = 20.0
MAX_THUMB_CASTERS = 12
MAX_WS_CLIENTS = 32
HUMAN_RUN_SECONDS = 2 * 3600
CHROME_ENSURE = os.environ.get("VIEWER_CHROME_ENSURE", "/opt/ghostship-agent-desktop/chrome-ensure")
ENSURE_SECONDS = 60      # chrome-ensure's own default timeout
BUSY_STALE = 30.0        # agent-side busy files older than this are abandoned
TAKEOVER_WAIT = 20.0     # how long a takeover waits for in-flight agent calls
INPUT_KINDS = frozenset({"tap", "pointer", "wheel", "key", "text", "navigate", "reload", "back", "forward",
                         "dialog"})

ACCESS_TEAM = os.environ.get("VIEWER_ACCESS_TEAM", "").strip()
ACCESS_AUD = os.environ.get("VIEWER_ACCESS_AUD", "").strip()
ACCESS_DISABLED = os.environ.get("VIEWER_ACCESS_DISABLED") == "1"
ACCESS_LEEWAY = 60
JWKS_MAX_AGE = 3600
JWKS_MIN_REFRESH = 30
WS_MAX_MESSAGE = 64 * 1024

# Windows virtual key codes Chrome needs for editing/navigation keys.
VK = {"Enter": 13, "Backspace": 8, "Tab": 9, "Escape": 27, "ArrowLeft": 37, "ArrowUp": 38,
      "ArrowRight": 39, "ArrowDown": 40, "Delete": 46, "Home": 36, "End": 35, "PageUp": 33,
      "PageDown": 34, "Insert": 45, " ": 32, "Shift": 16, "Control": 17, "Alt": 18, "Meta": 91}
KEY_TEXT = {"Enter": "\r", "Tab": "", " ": " "}
MOD_ALT, MOD_CTRL, MOD_META, MOD_SHIFT = 1, 2, 4, 8


def log(message: str) -> None:
    print(f"[viewer] {message}", file=sys.stderr, flush=True)


def err_name(exc: BaseException) -> str:
    if isinstance(exc, CdpError):
        return str(exc)[:160]
    return type(exc).__name__


# --------------------------------------------------------------------------
# Pure helpers (unit tested)
# --------------------------------------------------------------------------

def map_point(nx: float, ny: float, meta: dict) -> tuple[float, float]:
    """Map a point normalized to the displayed screencast frame to Input.* CSS px.

    The frame covers the visual viewport (deviceWidth x deviceHeight DIP).
    Input.dispatchMouseEvent coordinates are relative to the visual viewport
    and multiplied by the page scale (measured: with pinch zoom 2x, x=100
    lands 200 DIP in), so divide by pageScaleFactor. Scroll offsets are
    already reflected in the pixels and must not be added. offsetTop is the
    top-controls height that precedes the viewport in the frame.
    """
    def num(key: str, default: float) -> float:
        value = meta.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    width = max(num("deviceWidth", 0.0), 0.0)
    height = max(num("deviceHeight", 0.0), 0.0)
    top = max(num("offsetTop", 0.0), 0.0)
    scale = num("pageScaleFactor", 1.0)
    if scale <= 0:
        scale = 1.0
    nx = min(max(float(nx), 0.0), 1.0)
    ny = min(max(float(ny), 0.0), 1.0)
    x = nx * width / scale
    y = max(ny * height - top, 0.0) / scale
    return round(x, 2), round(y, 2)


def _check(regex: re.Pattern, value: object, what: str) -> str:
    if not isinstance(value, str) or not regex.fullmatch(value):
        raise ValueError(f"invalid {what}")
    return value


def _run_path(runs_dir: str, run_id: str, suffix: str) -> str:
    return os.path.join(runs_dir, _check(RUN_ID_RE, run_id, "run id") + suffix)


def _paused_path(runs_dir: str, target_id: str) -> str:
    return os.path.join(runs_dir, "paused", _check(TARGET_ID_RE, target_id, "target id"))


def _touch(path: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    os.close(fd)


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def is_paused(runs_dir: str, run_id: str) -> bool:
    return os.path.lexists(_run_path(runs_dir, run_id, ".pause"))


def sync_paused(runs_dir: str, target_ids) -> None:
    """Ensure ``paused/<target>`` exists for each id (validated first)."""
    paths = [_paused_path(runs_dir, tid) for tid in target_ids]
    os.makedirs(os.path.join(runs_dir, "paused"), mode=0o700, exist_ok=True)
    for path in paths:
        if not os.path.lexists(path):
            _touch(path)


def pause_run(runs_dir: str, run_id: str, target_ids, now: float | None = None) -> None:
    """Pause a run: block every member target first, then write the run marker."""
    marker = _run_path(runs_dir, run_id, ".pause")
    target_ids = list(target_ids)
    os.makedirs(runs_dir, mode=0o700, exist_ok=True)
    sync_paused(runs_dir, target_ids)
    body = json.dumps({"by": "viewer", "at": int(now if now is not None else time.time())}).encode()
    tmp = os.path.join(runs_dir, f".{run_id}.pause.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, body)
    finally:
        os.close(fd)
    os.replace(tmp, marker)


def resume_run(runs_dir: str, run_id: str, target_ids) -> None:
    """Resume: drop the run marker (so sync stops), then unblock every given target."""
    marker = _run_path(runs_dir, run_id, ".pause")
    paths = [_paused_path(runs_dir, tid) for tid in target_ids]
    _unlink(marker)
    for path in paths:
        _unlink(path)


def busy_targets(runs_dir: str, target_ids, now: float | None = None) -> list[str]:
    """Members with a fresh ``busy/<target>`` file (an agent call in flight)."""
    now = time.time() if now is None else now
    busy = []
    for tid in target_ids:
        try:
            mtime = os.stat(os.path.join(runs_dir, "busy", _check(TARGET_ID_RE, tid, "target id")),
                            follow_symlinks=False).st_mtime
        except FileNotFoundError:
            continue
        if now - mtime < BUSY_STALE:
            busy.append(tid)
    return busy


def takeover_decision(runs_dir: str, target_ids, waiting_since: float | None, now: float | None = None) -> str:
    """'go' when no member is busy; else 'wait' (within TAKEOVER_WAIT of the first refusal) or 'stuck'.

    Callers must have written the pause files before asking, so a busy file
    seen here belongs to a call that started before the pause.
    """
    now = time.time() if now is None else now
    if not busy_targets(runs_dir, target_ids, now):
        return "go"
    if waiting_since is not None and now - waiting_since >= TAKEOVER_WAIT:
        return "stuck"
    return "wait"


# --------------------------------------------------------------------------
# Cloudflare Access JWT verification (RS256, stdlib only)
# --------------------------------------------------------------------------

SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


class AuthError(Exception):
    pass


class UnknownKey(AuthError):
    pass


def b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", value):
        raise AuthError("bad encoding")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def rsa_pkcs1_sha256_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(signature) != k or k < 128:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify_jwt(token: str, keys: dict[str, tuple[int, int]], team: str, aud: str, now: float | None = None) -> dict:
    """Verify a Cloudflare Access JWT; return its claims or raise AuthError."""
    now = time.time() if now is None else now
    if not isinstance(token, str) or len(token) > 16384 or token.count(".") != 2:
        raise AuthError("malformed token")
    head_b64, body_b64, sig_b64 = token.split(".")
    try:
        header = json.loads(b64url_decode(head_b64))
        claims = json.loads(b64url_decode(body_b64))
    except ValueError:
        raise AuthError("malformed token") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError("malformed token")
    if header.get("alg") != "RS256":
        raise AuthError("unsupported alg")
    kid = header.get("kid")
    if not isinstance(kid, str) or kid not in keys:
        raise UnknownKey("unknown key")
    n, e = keys[kid]
    if not rsa_pkcs1_sha256_verify(n, e, f"{head_b64}.{body_b64}".encode(), b64url_decode(sig_b64)):
        raise AuthError("bad signature")
    audiences = claims.get("aud")
    audiences = [audiences] if isinstance(audiences, str) else audiences
    if not isinstance(audiences, list) or aud not in audiences:
        raise AuthError("wrong audience")
    if claims.get("iss") != f"https://{team}":
        raise AuthError("wrong issuer")
    exp, nbf = claims.get("exp"), claims.get("nbf")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or now > exp + ACCESS_LEEWAY:
        raise AuthError("expired")
    if nbf is not None and (not isinstance(nbf, (int, float)) or now + ACCESS_LEEWAY < nbf):
        raise AuthError("not yet valid")
    return claims


def parse_jwks(document: dict) -> dict[str, tuple[int, int]]:
    keys = {}
    for key in document.get("keys", []) if isinstance(document, dict) else []:
        if isinstance(key, dict) and key.get("kty") == "RSA" and isinstance(key.get("kid"), str):
            try:
                keys[key["kid"]] = (int.from_bytes(b64url_decode(key["n"]), "big"),
                                    int.from_bytes(b64url_decode(key["e"]), "big"))
            except (KeyError, AuthError, ValueError):
                continue
    return keys


def request_token(headers: dict) -> str | None:
    token = headers.get("cf-access-jwt-assertion")
    if token:
        return token
    for part in headers.get("cookie", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "CF_Authorization" and value:
            return value
    return None


class AccessVerifier:
    """Cloudflare Access keys cached from the team's certs endpoint."""

    def __init__(self, team: str, aud: str):
        self.team, self.aud = team, aud
        self.keys: dict[str, tuple[int, int]] = {}
        self.fetched = float("-inf")
        self.tried = float("-inf")
        self.lock = asyncio.Lock()

    def _fetch(self) -> dict:
        import urllib.request
        with urllib.request.urlopen(f"https://{self.team}/cdn-cgi/access/certs", timeout=10) as resp:
            return json.loads(resp.read(1 << 20))

    async def refresh(self, force: bool = False) -> None:
        async with self.lock:
            now = time.monotonic()
            if now - self.tried < JWKS_MIN_REFRESH and not (not self.keys and now - self.tried > 5):
                return
            if not force and self.keys and now - self.fetched < JWKS_MAX_AGE:
                return
            self.tried = now
            try:
                keys = parse_jwks(await asyncio.to_thread(self._fetch))
            except Exception as exc:
                log(f"access keys refresh failed: {type(exc).__name__}")
                return
            if keys:
                self.keys, self.fetched = keys, now

    async def check(self, headers: dict) -> None:
        token = request_token(headers)
        if not token:
            raise HttpError(401, "authentication required")
        if not self.keys or time.monotonic() - self.fetched > JWKS_MAX_AGE:
            await self.refresh()
        try:
            try:
                verify_jwt(token, self.keys, self.team, self.aud)
            except UnknownKey:
                await self.refresh(force=True)
                verify_jwt(token, self.keys, self.team, self.aud)
        except AuthError as exc:
            log(f"access denied: {exc}")
            raise HttpError(401, "authentication required") from None


def _read_small_json(path: str, limit: int = 16384):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        return None
    try:
        value = json.loads(data)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _str(value, limit: int = 200):
    return value[:limit] if isinstance(value, str) else None


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read_registry(runs_dir: str, run_id: str) -> dict | None:
    """Untrusted display data from ``<marker>.json``, reduced to known fields."""
    raw = _read_small_json(_run_path(runs_dir, run_id, ".json"))
    if raw is None:
        return None
    owner = raw.get("owner") if isinstance(raw.get("owner"), dict) else {}
    return {"label": _str(raw.get("label")),
            "identity": raw.get("identity") if raw.get("identity") in IDENTITIES else None,
            "opened_at": _num(raw.get("opened_at")),
            "owner": {key: _str(owner.get(key)) for key in ("harness", "model", "t3_thread_id", "t3_thread_title")}}


def read_state(runs_dir: str, target_id: str) -> dict | None:
    raw = _read_small_json(os.path.join(runs_dir, "state", _check(TARGET_ID_RE, target_id, "target id") + ".json"))
    if raw is None:
        return None
    return {"tool": _str(raw.get("tool"), 80), "action": _str(raw.get("action"), 200),
            "at": _num(raw.get("at")), "ok": raw.get("ok") if isinstance(raw.get("ok"), bool) else None}


def key_events(msg: dict) -> list[dict]:
    """Translate a client key message into Input.dispatchKeyEvent params."""
    key = _str(msg.get("key"), 32) or ""
    code = _str(msg.get("code"), 32) or ""
    mods = msg.get("mods") if isinstance(msg.get("mods"), int) else 0
    mods &= 15
    vk = msg.get("keyCode") if isinstance(msg.get("keyCode"), int) and 0 < msg.get("keyCode") < 256 else VK.get(key, 0)
    if not vk and len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    base = {"key": key, "code": code, "modifiers": mods, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
    kind = msg.get("kind", "press")
    text = KEY_TEXT.get(key, key if len(key) == 1 else "")
    if mods & (MOD_CTRL | MOD_ALT | MOD_META):
        text = ""
    down = dict(base, type="keyDown" if text else "rawKeyDown")
    if text:
        down.update(text=text, unmodifiedText=text)
    up = dict(base, type="keyUp")
    if kind == "down":
        return [down]
    if kind == "up":
        return [up]
    return [down, up]


def normalize_url(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("invalid url")
    url = raw.strip()
    if not url or len(url) > 4096:
        raise ValueError("invalid url")
    if url == "about:blank":
        return url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http and https URLs can be opened")
    return url


def origin_of(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme in ("http", "https") and parts.hostname:
        return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}"
    return url.split("#", 1)[0][:40] if url.startswith("about:") else parts.scheme + ":"


def parse_ports(spec: str) -> dict[str, int]:
    ports = {}
    for item in spec.split(","):
        name, _, port = item.strip().partition("=")
        if name in IDENTITIES and port.isdigit():
            ports[name] = int(port)
    return ports


# --------------------------------------------------------------------------
# Chrome connections
# --------------------------------------------------------------------------

class Browser:
    """One persistent browser-level CDP connection per identity.

    It never starts Chrome itself; App.ensure_browser does, for a human's
    new window, and wakes the reconnect loop through `wake`."""

    def __init__(self, app: "App", identity: str, port: int):
        self.app, self.identity, self.port = app, identity, port
        self.cdp: Cdp | None = None
        self.up = False
        self.targets: dict[str, dict] = {}
        self.windows: dict[str, int] = {}
        self.seen: dict[str, int] = {}
        self.first_seen: dict[str, float] = {}
        self.sticky: dict[str, str] = {}
        self._seq = 0
        self.wake = asyncio.Event()
        self.starting = asyncio.Lock()

    def alive(self) -> bool:
        return self.up and self.cdp is not None and not self.cdp._task.done()

    async def run(self) -> None:
        backoff = 1.0
        while True:
            queues = []
            try:
                self.cdp = await asyncio.wait_for(Cdp.connect(self.port), 8)
                for event in ("Target.targetCreated", "Target.targetInfoChanged", "Target.targetDestroyed"):
                    queues.append((event, self.cdp.listen(event)))
                await self.cdp.send("Target.setDiscoverTargets", {"discover": True}, timeout=10)
                self.up = True
                backoff = 1.0
                log(f"{self.identity} browser connected")
                await self.resync()
                self.app.changed()
                last = time.monotonic()
                while not self.cdp._task.done():
                    got = False
                    for event, queue in queues:
                        while not queue.empty():
                            self._event(event, queue.get_nowait()["params"])
                            got = True
                    if got:
                        await self._fill_windows()
                        self.app.changed()
                    if time.monotonic() - last > 5:
                        await self.resync()
                        last = time.monotonic()
                    for _ in range(10):  # wait up to 1s for the next target event
                        if self.cdp._task.done() or any(not queue.empty() for _, queue in queues):
                            break
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except (OSError, CdpError, asyncio.TimeoutError, ValueError, KeyError) as exc:
                if self.up:
                    log(f"{self.identity} browser lost: {err_name(exc)}")
            finally:
                was_up = self.up
                self.up = False
                if self.cdp is not None:
                    for _, queue in queues:
                        self.cdp.unlisten(queue)
                    try:
                        await self.cdp.close()
                    except Exception:
                        pass
                self.cdp = None
                self.targets.clear()
                self.windows.clear()
                self.sticky.clear()
                if was_up:
                    log(f"{self.identity} browser stopped")
                    await self.app.browser_down(self)
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), backoff)
                backoff = 1.0
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, 10.0)

    def _event(self, event: str, params: dict) -> None:
        if event == "Target.targetDestroyed":
            tid = params.get("targetId")
            self.targets.pop(tid, None)
            self.windows.pop(tid, None)
            self.sticky.pop(tid, None)
            return
        info = params.get("targetInfo") or {}
        tid = info.get("targetId")
        if info.get("type") != "page" or not isinstance(tid, str):
            return
        self._remember(info)

    def _remember(self, info: dict) -> None:
        tid = info["targetId"]
        if tid not in self.seen:
            self._seq += 1
            self.seen[tid] = self._seq
            self.first_seen[tid] = time.time()
        self.targets[tid] = info

    async def resync(self) -> None:
        infos = (await self.cdp.send("Target.getTargets", {}, timeout=10)).get("targetInfos", [])
        pages = {info["targetId"]: info for info in infos if info.get("type") == "page"}
        for tid in list(self.targets):
            if tid not in pages:
                self.targets.pop(tid, None)
                self.sticky.pop(tid, None)
        for info in pages.values():
            self._remember(info)
        self.windows = {tid: wid for tid, wid in self.windows.items() if tid in pages}
        await self._fill_windows(refresh=True)
        for tid in [t for t in self.seen if t not in pages]:
            self.seen.pop(tid, None)
            self.first_seen.pop(tid, None)

    async def _fill_windows(self, refresh: bool = False) -> None:
        for tid in list(self.targets):
            if refresh or tid not in self.windows:
                try:
                    reply = await self.cdp.send("Browser.getWindowForTarget", {"targetId": tid}, timeout=5)
                    self.windows[tid] = reply["windowId"]
                except (CdpError, KeyError):
                    self.windows.pop(tid, None)

    def runs(self) -> list[dict]:
        """Anchored runs with their member page targets (anchor first, then by first sight)."""
        if not self.alive():
            return []
        runs: dict[str, dict] = {}
        by_window: dict[int, str] = {}
        for tid, info in sorted(self.targets.items(), key=lambda item: self.seen.get(item[0], 0)):
            match = ANCHOR_RE.fullmatch(info.get("url", ""))
            if not match or match.group(1) in runs:
                continue
            run_id, expires = match.group(1), match.group(2)
            runs[run_id] = {"run_id": run_id, "identity": self.identity, "anchor": tid,
                            "expires_at": int(expires) if expires else None, "members": [tid]}
            window = self.windows.get(tid)
            if window is not None and window not in by_window:
                by_window[window] = run_id
        owner: dict[str, str] = {run["anchor"]: run_id for run_id, run in runs.items()}
        for tid in self.targets:
            run_id = by_window.get(self.windows.get(tid))
            if run_id and tid not in owner:
                owner[tid] = run_id
        for tid, run_id in self.sticky.items():
            if tid in self.targets and tid not in owner and run_id in runs:
                owner[tid] = run_id
        for _ in range(10):
            grew = False
            for tid, info in self.targets.items():
                opener = info.get("openerId")
                if tid not in owner and opener in owner:
                    owner[tid] = owner[opener]
                    self.sticky[tid] = owner[opener]
                    grew = True
            if not grew:
                break
        for tid in sorted(owner, key=lambda t: self.seen.get(t, 0)):
            run = runs[owner[tid]]
            if tid != run["anchor"]:
                run["members"].append(tid)
        return list(runs.values())


class Caster:
    """One viewer CDP session on a target: screencast (live or thumbnail), input, dialogs."""

    def __init__(self, app: "App", browser: Browser, tid: str, live: bool, size: tuple[int, int]):
        self.app, self.browser, self.tid, self.live = app, browser, tid, live
        self.cdp = browser.cdp
        self.size = size
        self.session: str | None = None
        self.clients: set[WsClient] = set()
        self.frame_text: str | None = None
        self.frame_data: str | None = None
        self.meta: dict = {}
        self.frame_at = 0.0
        self.first = asyncio.Event()
        self.used = time.monotonic()
        self.dialog: dict | None = None
        self.dead = False
        self._queues: list[asyncio.Queue] = []
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        reply = await self.cdp.send("Target.attachToTarget", {"targetId": self.tid, "flatten": True}, timeout=10)
        self.session = reply["sessionId"]
        frames = self.cdp.listen("Page.screencastFrame", self.session)
        self._queues.append(frames)
        self._tasks.append(asyncio.ensure_future(self._frames(frames)))
        if self.live:
            opening = self.cdp.listen("Page.javascriptDialogOpening", self.session)
            closed = self.cdp.listen("Page.javascriptDialogClosed", self.session)
            self._queues += [opening, closed]
            self._tasks.append(asyncio.ensure_future(self._dialogs(opening, closed)))
            await self.send("Page.enable")
        await self._cast()

    async def _cast(self) -> None:
        width, height = self.size
        await self.send("Page.startScreencast", {
            "format": "jpeg", "quality": LIVE_QUALITY if self.live else THUMB_QUALITY,
            "maxWidth": width, "maxHeight": height, "everyNthFrame": 1})

    async def resize(self, size: tuple[int, int]) -> None:
        if size[0] <= self.size[0] and size[1] <= self.size[1]:
            return
        self.size = (max(size[0], self.size[0]), max(size[1], self.size[1]))
        await self.send("Page.stopScreencast")
        await self._cast()

    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        if self.dead or self.cdp is None or self.cdp._task.done():
            raise CdpError("browser stopped")
        return await self.cdp.send(method, params or {}, self.session, timeout)

    async def _frames(self, queue: asyncio.Queue) -> None:
        interval = 1.0 / LIVE_FPS if self.live else THUMB_INTERVAL
        try:
            while True:
                params = (await queue.get())["params"]
                while not queue.empty():  # keep only the newest; ack the skipped ones
                    stale = params
                    params = queue.get_nowait()["params"]
                    await self.send("Page.screencastFrameAck", {"sessionId": stale["sessionId"]})
                received = time.monotonic()
                self.meta = params.get("metadata") or {}
                self.frame_data = params.get("data")
                self.frame_at = time.time()
                if self.live:
                    meta = {key: self.meta.get(key) for key in ("deviceWidth", "deviceHeight", "offsetTop",
                                                                 "pageScaleFactor", "scrollOffsetX", "scrollOffsetY")}
                    self.frame_text = json.dumps({"t": "frame", "target": self.tid, "meta": meta,
                                                  "at": self.frame_at, "data": self.frame_data})
                    for client in list(self.clients):
                        client.push_frame(self.tid, self.frame_text)
                self.first.set()
                await asyncio.sleep(max(0.0, interval - (time.monotonic() - received)))
                await self.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.dead:
                log(f"screencast ended: {err_name(exc)}")
            self.dead = True

    async def _dialogs(self, opening: asyncio.Queue, closed: asyncio.Queue) -> None:
        while True:
            waiters = [asyncio.ensure_future(opening.get()), asyncio.ensure_future(closed.get())]
            try:
                done, _pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for waiter in waiters:
                    if not waiter.done():
                        waiter.cancel()
            for waiter in done:
                message = waiter.result()
                if message["method"].endswith("Opening"):
                    params = message["params"]
                    self.dialog = {"t": "dialog", "target": self.tid, "kind": _str(params.get("type"), 20),
                                   "message": _str(params.get("message"), 2000) or "",
                                   "default": _str(params.get("defaultPrompt"), 2000) or "",
                                   "origin": origin_of(params.get("url") or "")}
                    payload = self.dialog
                else:
                    self.dialog = None
                    payload = {"t": "dialog-closed", "target": self.tid}
                for client in list(self.clients):
                    if client.target == self.tid:
                        client.push(payload)

    async def close(self) -> None:
        self.dead = True
        for task in self._tasks:
            task.cancel()
        if self.cdp is not None:
            for queue in self._queues:
                self.cdp.unlisten(queue)
            if self.session and not self.cdp._task.done():
                for method, params, session in (("Page.stopScreencast", {}, self.session),
                                                ("Target.detachFromTarget", {"sessionId": self.session}, None)):
                    try:
                        await self.cdp.send(method, params, session, timeout=3)
                    except Exception:
                        pass


# --------------------------------------------------------------------------
# HTTP / WebSocket plumbing
# --------------------------------------------------------------------------

class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


REASONS = {200: "OK", 204: "No Content", 301: "Moved Permanently", 400: "Bad Request", 403: "Forbidden",
           404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
           429: "Too Many Requests", 500: "Internal Server Error", 503: "Service Unavailable"}


class Request:
    def __init__(self, method: str, path: str, query: dict, headers: dict, body: bytes):
        self.method, self.path, self.query, self.headers, self.body = method, path, query, headers, body


async def read_request(reader: asyncio.StreamReader) -> Request | None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
        return None
    except asyncio.LimitOverrunError:
        raise HttpError(413, "request too large")
    lines = head.decode("latin-1").split("\r\n")
    try:
        method, target, _version = lines[0].split(" ", 2)
    except ValueError:
        raise HttpError(400, "bad request line")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
    length = headers.get("content-length", "0")
    if not length.isdigit() or int(length) > 4096:
        raise HttpError(413, "body too large")
    body = await reader.readexactly(int(length)) if int(length) else b""
    split = urllib.parse.urlsplit(target)
    query = {key: values[0] for key, values in urllib.parse.parse_qs(split.query).items()}
    return Request(method.upper(), urllib.parse.unquote(split.path), query, headers, body)


def response(status: int, body: bytes = b"", content_type: str = "application/json",
             extra: dict | None = None) -> bytes:
    headers = {"Content-Type": content_type, "Content-Length": str(len(body)), "Cache-Control": "no-store",
               "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
               "Connection": "close"}
    if content_type.startswith("text/html"):
        headers["Content-Security-Policy"] = CSP
        headers["X-Frame-Options"] = "DENY"
    headers.update(extra or {})
    head = f"HTTP/1.1 {status} {REASONS.get(status, 'Status')}\r\n" + "".join(
        f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n"
    return head.encode("latin-1") + body


def json_response(status: int, value) -> bytes:
    return response(status, json.dumps(value).encode())


def same_origin(req: Request) -> bool:
    origin = req.headers.get("origin")
    host = req.headers.get("host", "")
    if not origin or not host:
        return False
    parts = urllib.parse.urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == host.lower()


async def ws_send(writer: asyncio.StreamWriter, payload: bytes, opcode: int = 1) -> None:
    n = len(payload)
    if n < 126:
        header = bytes([0x80 | opcode, n])
    elif n < 65536:
        header = bytes([0x80 | opcode, 126]) + n.to_bytes(2, "big")
    else:
        header = bytes([0x80 | opcode, 127]) + n.to_bytes(8, "big")
    writer.write(header + payload)
    await writer.drain()


async def ws_recv(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """One complete client message (control frames returned as they come)."""
    parts: list[bytes] = []
    first_op = None
    total = 0
    while True:
        b0, b1 = await reader.readexactly(2)
        op, fin, n = b0 & 15, b0 & 0x80, b1 & 127
        if not b1 & 0x80:
            raise HttpError(400, "unmasked client frame")
        if n == 126:
            n = int.from_bytes(await reader.readexactly(2), "big")
        elif n == 127:
            n = int.from_bytes(await reader.readexactly(8), "big")
        total += n
        if total > WS_MAX_MESSAGE:
            raise HttpError(413, "message too large")
        mask = await reader.readexactly(4)
        data = await reader.readexactly(n)
        if n:
            data = (int.from_bytes(data, "big") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "big")).to_bytes(n, "big")
        if op >= 8:
            return op, data
        if first_op is None:
            first_op = op
        parts.append(data)
        if fin:
            return first_op, b"".join(parts)


class WsClient:
    def __init__(self, writer: asyncio.StreamWriter, identity: str, run_id: str, target: str,
                 size: tuple[int, int]):
        self.writer, self.identity, self.run_id, self.target, self.size = writer, identity, run_id, target, size
        self.msgs: collections.deque[str] = collections.deque(maxlen=64)
        self.frame: str | None = None
        self.wake = asyncio.Event()
        self.closed = False
        self.last_run = None

    def push(self, obj: dict) -> None:
        self.msgs.append(json.dumps(obj))
        self.wake.set()

    def push_frame(self, tid: str, text: str) -> None:
        if tid == self.target:
            self.frame = text
            self.wake.set()

    async def writer_loop(self) -> None:
        while not self.closed:
            await self.wake.wait()
            self.wake.clear()
            while self.msgs:
                await ws_send(self.writer, self.msgs.popleft().encode())
            if self.frame is not None:
                frame, self.frame = self.frame, None
                await ws_send(self.writer, frame.encode())


# --------------------------------------------------------------------------
# Application
# --------------------------------------------------------------------------

class App:
    def __init__(self, runs_dir: str, ports: dict[str, int]):
        self.runs_dir = runs_dir
        self.browsers = {identity: Browser(self, identity, port) for identity, port in ports.items()}
        self.live: dict[tuple[str, str], Caster] = {}
        self.thumbs: dict[tuple[str, str], Caster] = {}
        self.clients: set[WsClient] = set()
        self.thumb_gate = asyncio.Semaphore(3)
        self.access: AccessVerifier | None = None
        self.waiting: dict[str, float] = {}   # run_id -> first refused takeover input
        self.watchers: dict[str, asyncio.Task] = {}
        self.cast_lock = asyncio.Lock()

    # ---- run model -------------------------------------------------------
    def changed(self) -> None:
        self.sync_pauses()

    def all_runs(self) -> list[dict]:
        runs, seen = [], set()
        for browser in self.browsers.values():
            for run in browser.runs():
                if run["run_id"] not in seen:
                    seen.add(run["run_id"])
                    runs.append(run)
        return runs

    def find(self, run_id: str) -> tuple[Browser, dict]:
        _check(RUN_ID_RE, run_id, "run id")
        for run in self.all_runs():
            if run["run_id"] == run_id:
                return self.browsers[run["identity"]], run
        raise HttpError(404, "run not found")

    def sync_pauses(self) -> None:
        for run in self.all_runs():
            try:
                if is_paused(self.runs_dir, run["run_id"]):
                    sync_paused(self.runs_dir, run["members"])
            except (OSError, ValueError) as exc:
                log(f"pause sync failed: {err_name(exc)}")

    def sweep_orphans(self) -> None:
        """Drop paused/<target> files for targets no connected browser has (all must be up)."""
        if not self.browsers or not all(browser.alive() for browser in self.browsers.values()):
            return
        live = {tid for browser in self.browsers.values() for tid in browser.targets}
        paused_dir = os.path.join(self.runs_dir, "paused")
        try:
            names = os.listdir(paused_dir)
        except OSError:
            return
        for name in names:
            if TARGET_ID_RE.fullmatch(name) and name not in live:
                _unlink(os.path.join(paused_dir, name))

    def describe(self, run: dict, detail: bool = False) -> dict:
        browser = self.browsers[run["identity"]]
        registry = read_registry(self.runs_dir, run["run_id"]) or {}
        tabs, state, last_frame = [], None, 0.0
        for tid in run["members"]:
            info = browser.targets.get(tid, {})
            url = info.get("url", "")
            tab = {"target_id": tid, "title": _str(info.get("title"), 200) or "", "origin": origin_of(url),
                   "is_anchor": tid == run["anchor"], "opener": info.get("openerId") in run["members"]}
            if detail:
                tab["url"] = url[:2048]
            tabs.append(tab)
            current = read_state(self.runs_dir, tid)
            if current and current.get("at") is not None and (state is None or current["at"] > state["at"]):
                state = dict(current, target_id=tid)
            for caster in (self.live.get((run["identity"], tid)), self.thumbs.get((run["identity"], tid))):
                if caster is not None:
                    last_frame = max(last_frame, caster.frame_at)
        primary = state["target_id"] if state else (tabs[-1]["target_id"] if tabs else None)
        return {"run_id": run["run_id"], "identity": run["identity"], "label": registry.get("label"),
                "owner": registry.get("owner"), "opened_at": registry.get("opened_at"),
                "seen_at": browser.first_seen.get(run["anchor"]), "expires_at": run["expires_at"],
                "registered": bool(registry), "tabs": tabs, "paused": is_paused(self.runs_dir, run["run_id"]),
                "state": state, "last_frame_at": last_frame or None, "primary_target": primary}

    # ---- casters ---------------------------------------------------------
    async def browser_down(self, browser: Browser) -> None:
        for table in (self.live, self.thumbs):
            for key in [key for key in table if key[0] == browser.identity]:
                caster = table.pop(key)
                await caster.close()
        for client in list(self.clients):
            client.push({"t": "status", "browser": "stopped"})

    async def live_caster(self, browser: Browser, tid: str, size: tuple[int, int]) -> Caster:
        key = (browser.identity, tid)
        async with self.cast_lock:
            caster = self.live.get(key)
            if caster is not None and caster.dead:
                self.live.pop(key, None)
                await caster.close()
                caster = None
            if caster is None:
                caster = Caster(self, browser, tid, True, size)
                try:
                    await caster.start()
                except BaseException:
                    await caster.close()
                    raise
                self.live[key] = caster
            else:
                await caster.resize(size)
            return caster

    async def release(self, client: WsClient) -> None:
        caster = self.live.get((client.identity, client.target))
        if caster is not None:
            caster.clients.discard(client)

    async def thumb(self, browser: Browser, tid: str) -> bytes | None:
        key = (browser.identity, tid)
        live = self.live.get(key)
        if live is not None and live.frame_data and not live.dead:
            return base64.b64decode(live.frame_data)
        caster = self.thumbs.get(key)
        if caster is not None and caster.dead:
            self.thumbs.pop(key, None)
            await caster.close()
            caster = None
        if caster is None:
            if len(self.thumbs) >= MAX_THUMB_CASTERS:
                oldest = min(self.thumbs, key=lambda k: self.thumbs[k].used)
                await self.thumbs.pop(oldest).close()
            caster = Caster(self, browser, tid, False, THUMB_SIZE)
            self.thumbs[key] = caster
            try:
                async with self.thumb_gate:
                    await caster.start()
            except Exception:
                self.thumbs.pop(key, None)
                await caster.close()
                raise
        caster.used = time.monotonic()
        try:
            await asyncio.wait_for(caster.first.wait(), 3.0)
        except asyncio.TimeoutError:
            return None
        return base64.b64decode(caster.frame_data) if caster.frame_data else None

    async def housekeeping(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(0.5)
            tick += 1
            self.sync_pauses()
            if tick % 10:
                continue
            now = time.monotonic()
            for key, caster in list(self.thumbs.items()):
                gone = key[1] not in self.browsers[key[0]].targets
                if caster.dead or gone or now - caster.used > THUMB_IDLE:
                    self.thumbs.pop(key, None)
                    await caster.close()
            for key, caster in list(self.live.items()):
                if caster.dead or not caster.clients or key[1] not in self.browsers[key[0]].targets:
                    self.live.pop(key, None)
                    await caster.close()
            if tick % 60 == 0:
                self.sweep_orphans()

    # ---- actions ---------------------------------------------------------
    def pause(self, run: dict) -> None:
        pause_run(self.runs_dir, run["run_id"], run["members"])

    def resume(self, run: dict) -> None:
        resume_run(self.runs_dir, run["run_id"], run["members"])
        self.waiting.pop(run["run_id"], None)
        self.sweep_orphans()  # tabs that closed while paused are no longer members

    async def ensure_browser(self, browser: Browser) -> None:
        """Start an idle-stopped Chrome (chrome-ensure) and wait for the connection."""
        async with browser.starting:
            if browser.alive():
                return
            proc = await asyncio.create_subprocess_exec(
                CHROME_ENSURE, browser.identity, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            try:
                _, err = await asyncio.wait_for(proc.communicate(), ENSURE_SECONDS + 10)
            except asyncio.TimeoutError:
                proc.kill()
                raise HttpError(503, "browser did not start")
            if proc.returncode != 0:
                log(f"chrome-ensure {browser.identity} failed: {err.decode(errors='replace').strip()[:300]}")
                raise HttpError(503, "browser did not start")
            browser.wake.set()
            deadline = time.monotonic() + 15
            while not browser.alive():
                if time.monotonic() > deadline:
                    raise HttpError(503, "browser started but is not reachable")
                await asyncio.sleep(0.2)

    async def new_run(self, identity: str) -> dict:
        browser = self.browsers.get(identity)
        if browser is None:
            raise HttpError(400, "unknown identity")
        await self.ensure_browser(browser)
        cdp = browser.cdp
        run_id = secrets.token_hex(16)
        now = int(time.time())
        anchor_url = f"about:blank#ghostship-window-{run_id}.{now + HUMAN_RUN_SECONDS}"
        anchor = (await cdp.send("Target.createTarget", {"url": anchor_url, "newWindow": True, "background": True},
                                 timeout=15))["targetId"]
        os.makedirs(self.runs_dir, mode=0o700, exist_ok=True)
        record = {"schema": 1, "run_id": run_id, "identity": identity, "label": "Human session",
                  "opened_at": now, "owner": {"harness": "human", "model": None, "t3_thread_id": None,
                                              "t3_thread_title": None}}
        tmp = os.path.join(self.runs_dir, f".{run_id}.json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(record, handle)
        os.replace(tmp, os.path.join(self.runs_dir, f"{run_id}.json"))
        # Open the working tab from the anchor itself so Chrome puts it in this
        # window without focusing anything. The anchor is our own about:blank page.
        session = (await cdp.send("Target.attachToTarget", {"targetId": anchor, "flatten": True}))["sessionId"]
        try:
            await cdp.send("Runtime.evaluate", {"expression": "void window.open('about:blank', '_blank')",
                                                "userGesture": True}, session, timeout=10)
        finally:
            try:
                await cdp.send("Target.detachFromTarget", {"sessionId": session}, timeout=5)
            except Exception:
                pass
        await asyncio.sleep(0.3)
        await browser.resync()
        return {"run_id": run_id, "identity": identity}

    # ---- HTTP ------------------------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                req = await read_request(reader)
                if req is None:
                    return
                result = await self.route(req, reader, writer)
            except HttpError as exc:
                result = json_response(exc.status, {"error": exc.message})
            except ValueError as exc:
                result = json_response(400, {"error": str(exc)[:200]})
            except CdpError as exc:
                log(f"request failed: {err_name(exc)}")
                result = json_response(503, {"error": "browser command failed"})
            except (ConnectionError, asyncio.IncompleteReadError):
                return
            except Exception as exc:  # never leak a traceback to the client
                log(f"request failed: {err_name(exc)}")
                result = json_response(500, {"error": "internal error"})
            if result:
                writer.write(result)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def route(self, req: Request, reader, writer) -> bytes | None:
        if self.access is not None:
            await self.access.check(req.headers)
        path = req.path
        if path == "/agents":
            return response(301, b"", "text/plain", {"Location": "/agents/"})
        if path.startswith("/agents/"):
            path = path[len("/agents/"):]
        elif path.startswith("/"):
            path = path[1:]
        parts = path.split("/")
        if req.method == "POST":
            if req.headers.get("x-ghostship-viewer") != "1" or ("origin" in req.headers and not same_origin(req)):
                raise HttpError(403, "forbidden")
        elif req.method != "GET":
            raise HttpError(405, "method not allowed")

        if req.method == "GET" and path in STATIC:
            name, content_type = STATIC[path]
            with open(os.path.join(HERE, name), "rb") as handle:
                return response(200, handle.read(), content_type)
        if path == "healthz":
            return json_response(200, {"ok": True})
        if parts[:2] != ["api", "runs"]:
            raise HttpError(404, "not found")
        rest = parts[2:]
        if req.method == "GET" and not rest:
            return json_response(200, {
                "browsers": {identity: ("up" if browser.alive() else "stopped")
                             for identity, browser in self.browsers.items()},
                "now": time.time(),
                "runs": [self.describe(run) for run in self.all_runs()]})
        if req.method == "POST" and rest == ["new"]:
            return json_response(200, await self.new_run(req.query.get("identity", "")))
        if len(rest) != 2:
            raise HttpError(404, "not found")
        browser, run = self.find(rest[0])
        action = rest[1]
        if req.method == "POST" and action in ("pause", "resume"):
            self.pause(run) if action == "pause" else self.resume(run)
            return json_response(200, {"run_id": run["run_id"], "paused": action == "pause"})
        if req.method == "GET" and action == "thumb":
            tid = req.query.get("target") or self.describe(run)["primary_target"]
            if tid not in run["members"]:
                raise HttpError(404, "target not in run")
            data = await self.thumb(browser, tid)
            if not data:
                return response(204)
            return response(200, data, "image/jpeg", {"Cache-Control": "private, max-age=2"})
        if req.method == "GET" and action == "stream":
            await self.websocket(req, reader, writer, browser, run)
            return None
        raise HttpError(404, "not found")

    async def websocket(self, req: Request, reader, writer, browser: Browser, run: dict) -> None:
        protocols = [item.strip() for item in req.headers.get("sec-websocket-protocol", "").split(",") if item.strip()]
        if req.headers.get("upgrade", "").lower() != "websocket" or "sec-websocket-key" not in req.headers:
            raise HttpError(400, "websocket upgrade required")
        if not same_origin(req) or not ("ghostship-viewer" in protocols or req.headers.get("x-ghostship-viewer") == "1"):
            raise HttpError(403, "forbidden")
        if len(self.clients) >= MAX_WS_CLIENTS:
            raise HttpError(429, "too many viewers")
        tid = req.query.get("target") or self.describe(run)["primary_target"]
        if tid not in run["members"]:
            tid = run["members"][-1]
        size = self.client_size(req.query.get("w"), req.query.get("h"))
        accept = base64.b64encode(hashlib.sha1(
            (req.headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        extra = "Sec-WebSocket-Protocol: ghostship-viewer\r\n" if "ghostship-viewer" in protocols else ""
        writer.write((f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept}\r\n{extra}\r\n").encode())
        await writer.drain()
        client = WsClient(writer, browser.identity, run["run_id"], tid, size)
        self.clients.add(client)
        tasks = []
        try:
            tasks = [asyncio.ensure_future(client.writer_loop())]
            try:
                await self.subscribe(client, browser, tid)
            except CdpError as exc:
                log(f"stream attach failed: {err_name(exc)}")
                client.push({"t": "error", "error": "could not attach to the tab"})
            tasks.append(asyncio.ensure_future(self.run_updates(client)))
            while True:
                op, data = await ws_recv(reader)
                if op == 8:
                    break
                if op == 9:
                    writer.write(bytes([0x8A, len(data)]) + data if len(data) < 126 else b"")
                    continue
                if op != 1:
                    continue
                try:
                    await self.on_message(client, json.loads(data))
                except (ValueError, KeyError, TypeError, HttpError, CdpError, OSError) as exc:
                    message = exc.message if isinstance(exc, HttpError) else (
                        "browser command failed" if isinstance(exc, CdpError) else str(exc)[:200])
                    if isinstance(exc, CdpError):
                        log(f"input failed: {err_name(exc)}")
                    client.push({"t": "error", "error": message})
                for task in tasks:
                    if task.done():
                        raise ConnectionError("writer ended")
        except (asyncio.IncompleteReadError, ConnectionError, HttpError):
            pass
        finally:
            client.closed = True
            client.wake.set()
            self.clients.discard(client)
            await self.release(client)
            for task in tasks:
                task.cancel()

    @staticmethod
    def client_size(w, h) -> tuple[int, int]:
        def clamp(value, default):
            try:
                return min(max(int(float(value)), 160), MAX_CAST_EDGE)
            except (TypeError, ValueError):
                return default
        return clamp(w, 1280), clamp(h, 800)

    async def subscribe(self, client: WsClient, browser: Browser, tid: str) -> None:
        await self.release(client)
        client.target = tid
        client.frame = None
        client.push({"t": "tab", "target": tid})
        caster = await self.live_caster(browser, tid, client.size)
        caster.clients.add(client)
        if caster.frame_text:
            client.push_frame(tid, caster.frame_text)
        if caster.dialog:
            client.push(caster.dialog)

    async def run_updates(self, client: WsClient) -> None:
        while not client.closed:
            try:
                browser, run = self.find(client.run_id)
                described = self.describe(run, detail=True)
                if described != client.last_run:
                    client.last_run = described
                    client.push({"t": "run", "run": described})
                caster = self.live.get((client.identity, client.target))
                if client.target not in run["members"] or caster is None or caster.dead:
                    tid = client.target if client.target in run["members"] else run["members"][-1]
                    await self.subscribe(client, browser, tid)
            except HttpError:
                client.push({"t": "gone", "browser": "up" if self.browsers[client.identity].alive() else "stopped"})
            except (CdpError, OSError, ValueError) as exc:
                log(f"stream update failed: {err_name(exc)}")
            await asyncio.sleep(1)

    async def on_message(self, client: WsClient, msg: dict) -> None:
        if not isinstance(msg, dict):
            raise ValueError("bad message")
        kind = msg.get("t")
        browser, run = self.find(client.run_id)
        if kind == "viewport":
            client.size = self.client_size(msg.get("w"), msg.get("h"))
            caster = self.live.get((browser.identity, client.target))
            if caster:
                await caster.resize(client.size)
            return
        if kind == "select-tab":
            tid = msg.get("target")
            if tid not in run["members"]:
                raise ValueError("tab not in this run")
            await self.subscribe(client, browser, tid)
            return
        if kind in ("pause", "resume"):
            self.pause(run) if kind == "pause" else self.resume(run)
            client.last_run = None
            return
        if kind not in INPUT_KINDS:
            raise ValueError("unknown message")
        if client.target not in run["members"]:
            raise ValueError("tab closed")
        hover = kind == "pointer" and msg.get("kind") == "move" and not msg.get("buttons")
        if client.target == run["anchor"]:
            if hover:
                return
            raise ValueError("the home tab is read-only")
        registry = read_registry(self.runs_dir, run["run_id"]) or {}
        human = (registry.get("owner") or {}).get("harness") == "human"
        if not human:
            paused = is_paused(self.runs_dir, run["run_id"])
            if hover and not paused:
                return  # bare hover over a running agent is not a takeover; don't disturb its page
            if not paused:  # any human input pauses the agent first (until an explicit Resume)
                self.pause(run)
                client.last_run = None
            if not self.may_input(run):
                return
        caster = await self.live_caster(browser, client.target, client.size)
        caster.clients.add(client)
        await self.input(caster, kind, msg)

    def run_clients(self, run_id: str):
        return [client for client in self.clients if client.run_id == run_id]

    def may_input(self, run: dict) -> bool:
        """After the pause files exist, let input through only once no member is mid-call."""
        run_id = run["run_id"]
        decision = takeover_decision(self.runs_dir, run["members"], self.waiting.get(run_id))
        if decision == "go":
            self.waiting.pop(run_id, None)
            return True
        first = run_id not in self.waiting
        self.waiting.setdefault(run_id, time.time())
        if decision == "stuck":
            for client in self.run_clients(run_id):
                client.push({"t": "busy", "stuck": True})
        elif first:
            for client in self.run_clients(run_id):
                client.push({"t": "busy"})
        watcher = self.watchers.get(run_id)
        if watcher is None or watcher.done():
            self.watchers[run_id] = asyncio.ensure_future(self.watch_busy(run_id))
        return False

    async def watch_busy(self, run_id: str) -> None:
        """Poll busy files every 100 ms; tell the UI when control is free or the wait gave up."""
        while True:
            await asyncio.sleep(0.1)
            try:
                _, run = self.find(run_id)
            except HttpError:
                self.waiting.pop(run_id, None)
                return
            decision = takeover_decision(self.runs_dir, run["members"], self.waiting.get(run_id))
            if decision == "go":
                self.waiting.pop(run_id, None)
                for client in self.run_clients(run_id):
                    client.push({"t": "ready"})
                return
            if decision == "stuck":  # keep refusing; the next input re-checks ("try again")
                for client in self.run_clients(run_id):
                    client.push({"t": "busy", "stuck": True})
                return

    async def input(self, caster: Caster, kind: str, msg: dict) -> None:
        meta = caster.meta

        def point():
            if not meta.get("deviceWidth"):
                raise ValueError("no frame yet")
            return map_point(float(msg.get("x", 0)), float(msg.get("y", 0)), meta)

        mods = msg.get("mods") if isinstance(msg.get("mods"), int) else 0
        mods &= 15
        if kind == "tap":
            x, y = point()
            base = {"x": x, "y": y, "modifiers": mods}
            await caster.send("Input.dispatchMouseEvent", dict(base, type="mouseMoved"))
            clicks = 2 if msg.get("double") else 1
            for count in range(1, clicks + 1):
                await caster.send("Input.dispatchMouseEvent", dict(base, type="mousePressed", button="left",
                                                                   buttons=1, clickCount=count))
                await caster.send("Input.dispatchMouseEvent", dict(base, type="mouseReleased", button="left",
                                                                   buttons=0, clickCount=count))
        elif kind == "pointer":
            x, y = point()
            action = {"down": "mousePressed", "up": "mouseReleased", "move": "mouseMoved"}.get(msg.get("kind"))
            if action is None:
                raise ValueError("bad pointer kind")
            button = msg.get("button") if msg.get("button") in ("left", "middle", "right") else "none"
            params = {"type": action, "x": x, "y": y, "modifiers": mods, "button": button,
                      "buttons": msg.get("buttons") if isinstance(msg.get("buttons"), int) else 0}
            if action != "mouseMoved":
                params["clickCount"] = min(max(int(msg.get("clickCount", 1)), 1), 3)
            await caster.send("Input.dispatchMouseEvent", params)
        elif kind == "wheel":
            x, y = point()
            dx = max(min(float(msg.get("dx", 0)), 5000.0), -5000.0)
            dy = max(min(float(msg.get("dy", 0)), 5000.0), -5000.0)
            await caster.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx,
                                                          "deltaY": dy, "modifiers": mods})
        elif kind == "key":
            for params in key_events(msg):
                await caster.send("Input.dispatchKeyEvent", params)
        elif kind == "text":
            text = msg.get("text")
            if not isinstance(text, str) or not text or len(text) > 2000:
                raise ValueError("bad text")
            await caster.send("Input.insertText", {"text": text})
        elif kind == "navigate":
            await caster.send("Page.navigate", {"url": normalize_url(msg.get("url"))})
        elif kind == "reload":
            await caster.send("Page.reload", {})
        elif kind in ("back", "forward"):
            history = await caster.send("Page.getNavigationHistory")
            index = history.get("currentIndex", 0) + (-1 if kind == "back" else 1)
            entries = history.get("entries", [])
            if 0 <= index < len(entries):
                await caster.send("Page.navigateToHistoryEntry", {"entryId": entries[index]["id"]})
        elif kind == "dialog":
            params = {"accept": bool(msg.get("accept"))}
            if isinstance(msg.get("text"), str):
                params["promptText"] = msg["text"][:2000]
            await caster.send("Page.handleJavaScriptDialog", params)
        else:
            raise ValueError("unknown message")


async def main() -> None:
    ports = parse_ports(CDP_PORTS_SPEC)
    if not ports:
        log("no CDP ports configured")
        sys.exit(2)
    app = App(RUNS_DIR, ports)
    if ACCESS_TEAM and ACCESS_AUD:
        app.access = AccessVerifier(ACCESS_TEAM, ACCESS_AUD)
        await app.access.refresh(force=True)
        if not app.access.keys:
            log("warning: Cloudflare Access keys not loaded yet; requests are refused until they are")
    elif ACCESS_DISABLED:
        log("WARNING: Cloudflare Access verification is DISABLED (VIEWER_ACCESS_DISABLED=1); lab use only")
    else:
        log("refusing to start: set VIEWER_ACCESS_TEAM and VIEWER_ACCESS_AUD (or VIEWER_ACCESS_DISABLED=1 in a lab)")
        sys.exit(2)
    for browser in app.browsers.values():
        asyncio.ensure_future(browser.run())
    asyncio.ensure_future(app.housekeeping())
    server = await asyncio.start_server(app.handle, BIND, PORT, limit=32 * 1024)
    log(f"listening on {BIND}:{PORT} ({', '.join(f'{k}={v}' for k, v in ports.items())})")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
