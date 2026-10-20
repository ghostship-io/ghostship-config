"""Load-bearing checks for the agent viewer: input mapping, pause/busy protocol, Chrome start, Access JWT auth."""
import base64
import hashlib
import json
import asyncio
import secrets
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server

META = {"deviceWidth": 1568, "deviceHeight": 768, "offsetTop": 0, "pageScaleFactor": 1,
        "scrollOffsetX": 0, "scrollOffsetY": 0}


class MapPointTest(unittest.TestCase):
    def test_plain_frame_maps_to_viewport_css_px(self):
        """Catches scaling by the displayed image size instead of the device viewport (clicks land off-target)."""
        self.assertEqual(server.map_point(0.5, 0.25, META), (784.0, 192.0))
        self.assertEqual(server.map_point(0, 0, META), (0.0, 0.0))
        self.assertEqual(server.map_point(1, 1, META), (1568.0, 768.0))

    def test_scroll_offset_is_not_added(self):
        """Catches adding scrollOffsetX/Y: Input coordinates are viewport-relative, so a scrolled page would be mis-hit."""
        scrolled = dict(META, scrollOffsetX=200, scrollOffsetY=5000)
        self.assertEqual(server.map_point(0.5, 0.5, scrolled), server.map_point(0.5, 0.5, META))

    def test_page_scale_divides(self):
        """Catches ignoring pinch zoom: Chrome multiplies Input coords by pageScaleFactor (measured live)."""
        self.assertEqual(server.map_point(0.5, 0.5, dict(META, pageScaleFactor=2)), (392.0, 192.0))

    def test_offset_top_is_subtracted_and_clamped(self):
        """Catches ignoring the top-controls offset, and negative coordinates from taps on that strip."""
        meta = dict(META, offsetTop=56)
        self.assertEqual(server.map_point(0.5, 0.5, meta), (784.0, 328.0))
        self.assertEqual(server.map_point(0.5, 0.01, meta), (784.0, 0.0))

    def test_out_of_range_and_bad_metadata(self):
        """Catches clicks outside the window from overshooting drags and crashes on bogus metadata."""
        self.assertEqual(server.map_point(-1, 2, META), (0.0, 768.0))
        self.assertEqual(server.map_point(0.5, 0.5, dict(META, pageScaleFactor=0)), (784.0, 384.0))
        self.assertEqual(server.map_point(0.5, 0.5, dict(META, pageScaleFactor="x")), (784.0, 384.0))


class PauseProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.runs = os.path.join(self.root, "runs")
        os.mkdir(self.runs, 0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def paused(self):
        return sorted(os.listdir(os.path.join(self.runs, "paused")))

    def test_pause_blocks_every_member_and_resume_clears(self):
        """Catches a pause that leaves a tab/popup drivable or a resume that leaves the gate closed."""
        members = ["AAAA1111", "BBBB2222", "CCCC3333"]
        server.pause_run(self.runs, "run_1", members, now=1700000000)
        self.assertEqual(self.paused(), members)
        with open(os.path.join(self.runs, "run_1.pause")) as handle:
            self.assertEqual(json.load(handle), {"by": "viewer", "at": 1700000000})
        self.assertTrue(server.is_paused(self.runs, "run_1"))
        server.sync_paused(self.runs, members + ["DDDD4444"])  # a popup opened while paused
        self.assertIn("DDDD4444", self.paused())
        server.resume_run(self.runs, "run_1", members + ["DDDD4444"])
        self.assertFalse(server.is_paused(self.runs, "run_1"))
        self.assertEqual(self.paused(), [])
        self.assertEqual(sorted(os.listdir(self.runs)), ["paused"])  # no temp files left behind

    def test_crafted_ids_cannot_escape_runs_dir(self):
        """Catches path traversal: run/target ids come from URLs and Chrome and must not write outside runs/."""
        for bad in ("../x", "..", "a/b", "", "x" * 65, "a\x00b", "/etc/passwd", ".hidden"):
            with self.assertRaises(ValueError):
                server.pause_run(self.runs, bad, ["AAAA1111"])
            with self.assertRaises(ValueError):
                server.resume_run(self.runs, bad, [])
        for bad in ("../../escape", "..", "a.b", "", "x/y"):
            with self.assertRaises(ValueError):
                server.pause_run(self.runs, "run_2", ["AAAA1111", bad])
        # A rejected target id must not leave a half-applied pause behind.
        self.assertFalse(server.is_paused(self.runs, "run_2"))
        self.assertFalse(os.path.exists(os.path.join(self.runs, "paused", "AAAA1111")))
        self.assertEqual(sorted(os.listdir(self.root)), ["runs"])

    def test_symlinked_pause_entry_is_not_followed(self):
        """Catches following a planted symlink in paused/ to create a file elsewhere."""
        os.mkdir(os.path.join(self.runs, "paused"), 0o700)
        outside = os.path.join(self.root, "outside")
        os.symlink(outside, os.path.join(self.runs, "paused", "AAAA1111"))
        server.pause_run(self.runs, "run_3", ["AAAA1111"])
        self.assertFalse(os.path.exists(outside))


class TakeoverBusyTest(unittest.TestCase):
    def test_human_input_waits_for_in_flight_agent_call(self):
        """Catches human input overlapping an in-flight agent action (busy file ignored, stale or not)."""
        with tempfile.TemporaryDirectory() as runs:
            os.mkdir(os.path.join(runs, "busy"))
            now = 1_800_000_000.0
            members = ["AAAA1111", "BBBB2222"]
            self.assertEqual(server.takeover_decision(runs, members, None, now), "go")
            busy = os.path.join(runs, "busy", "BBBB2222")
            open(busy, "w").close()
            os.utime(busy, (now - 5, now - 5))  # fresh: an agent call is mid-flight
            self.assertEqual(server.takeover_decision(runs, members, None, now), "wait")
            self.assertEqual(server.takeover_decision(runs, members, now - 10, now), "wait")
            self.assertEqual(server.takeover_decision(runs, members, now - 20, now), "stuck")
            self.assertEqual(server.takeover_decision(runs, ["AAAA1111"], None, now), "go")  # other run's tab
            os.utime(busy, (now - 31, now - 31))  # abandoned (gate refreshes every 10 s)
            self.assertEqual(server.takeover_decision(runs, members, now - 20, now), "go")
            os.unlink(busy)
            self.assertEqual(server.takeover_decision(runs, members, None, now), "go")
            with self.assertRaises(ValueError):
                server.takeover_decision(runs, ["../paused"], None, now)


class EnsureBrowserTest(unittest.TestCase):
    class FakeBrowser:
        identity = "personal"

        def __init__(self):
            self.wake = asyncio.Event()
            self.starting = asyncio.Lock()

        def alive(self):
            return self.wake.is_set()  # connects once the reconnect loop is woken

    def _ensure(self, script: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "chrome-ensure")
            with open(path, "w") as handle:
                handle.write(f"#!/bin/sh\necho \"$1\" >> {tmp}/calls\n{script}\n")
            os.chmod(path, 0o755)
            server.CHROME_ENSURE = path
            browser = self.FakeBrowser()

            async def twice():
                return await asyncio.gather(server.App.ensure_browser(None, browser),
                                            server.App.ensure_browser(None, browser), return_exceptions=True)
            results = asyncio.run(twice())
            calls = open(os.path.join(tmp, "calls")).read().split() if os.path.exists(os.path.join(tmp, "calls")) else []
            return results, calls

    def test_new_window_starts_a_stopped_browser_once(self):
        """Catches '+ Personal' failing with 'browser stopped' after the idle stop, or racing two starts."""
        results, calls = self._ensure("exit 0")
        self.assertEqual(results, [None, None])
        self.assertEqual(calls, ["personal"])

    def test_failed_start_is_reported(self):
        """Catches a failed chrome-ensure being treated as a started browser."""
        results, _ = self._ensure("echo no >&2; exit 1")
        self.assertTrue(all(isinstance(r, server.HttpError) and r.status == 503 for r in results))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _prime(bits: int) -> int:
    while True:
        n = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and all(
                pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)):
            return n


class AccessJwtTest(unittest.TestCase):
    TEAM, AUD = "example.cloudflareaccess.com", "aud-123"

    @classmethod
    def setUpClass(cls):
        e = 65537
        while True:
            p, q = _prime(512), _prime(512)
            phi = (p - 1) * (q - 1)
            if p != q and phi % e:
                break
        cls.n, cls.d = p * q, pow(e, -1, phi)
        cls.keys = {"k1": (cls.n, e)}
        cls.jwks = {"keys": [{"kty": "RSA", "kid": "k1", "n": _b64(cls.n.to_bytes(128, "big")),
                              "e": _b64(e.to_bytes(3, "big"))}]}

    def token(self, claims, alg="RS256", kid="k1", tamper=False):
        head = _b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
        body = _b64(json.dumps(claims).encode())
        if alg == "none":
            return f"{head}.{body}."
        digest = hashlib.sha256(f"{head}.{body}".encode()).digest()
        t = server.SHA256_DIGEST_INFO + digest
        em = b"\x00\x01" + b"\xff" * (128 - len(t) - 3) + b"\x00" + t
        sig = pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(128, "big")
        if tamper:
            sig = bytes([sig[0] ^ 1]) + sig[1:]
        return f"{head}.{body}.{_b64(sig)}"

    def test_access_jwt_table(self):
        """Catches an unauthenticated container-network peer driving agent browsers (forged/expired/foreign JWTs)."""
        now = 1_800_000_000
        good = {"aud": [self.AUD], "iss": f"https://{self.TEAM}", "exp": now + 300, "nbf": now - 10,
                "email": "op@example.com"}
        keys = server.parse_jwks(self.jwks)
        self.assertEqual(keys, self.keys)
        cases = [
            ("valid", self.token(good), True),
            ("valid, aud as string", self.token(dict(good, aud=self.AUD)), True),
            ("exp within leeway", self.token(dict(good, exp=now - 30)), True),
            ("wrong aud", self.token(dict(good, aud=["other"])), False),
            ("wrong iss", self.token(dict(good, iss="https://evil.cloudflareaccess.com")), False),
            ("expired", self.token(dict(good, exp=now - 120)), False),
            ("not yet valid", self.token(dict(good, nbf=now + 300)), False),
            ("missing exp", self.token({k: v for k, v in good.items() if k != "exp"}), False),
            ("bad signature", self.token(good, tamper=True), False),
            ("alg none", self.token(good, alg="none"), False),
            ("alg HS256", self.token(good, alg="HS256"), False),
            ("unknown kid", self.token(good, kid="k2"), False),
            ("garbage", "not.a.jwt", False),
            ("claims swapped after signing", self.token(good).rsplit(".", 2)[0] + "."
             + _b64(json.dumps(dict(good, aud=["x"])).encode()) + "." + self.token(good).rsplit(".", 1)[1], False),
        ]
        for name, token, ok in cases:
            with self.subTest(name):
                if ok:
                    self.assertEqual(server.verify_jwt(token, keys, self.TEAM, self.AUD, now)["email"], "op@example.com")
                else:
                    with self.assertRaises(server.AuthError):
                        server.verify_jwt(token, keys, self.TEAM, self.AUD, now)
        self.assertEqual(server.request_token({"cookie": "a=b; CF_Authorization=tok"}), "tok")
        self.assertEqual(server.request_token({"cf-access-jwt-assertion": "hdr", "cookie": "CF_Authorization=c"}), "hdr")
        self.assertIsNone(server.request_token({}))


if __name__ == "__main__":
    unittest.main()
