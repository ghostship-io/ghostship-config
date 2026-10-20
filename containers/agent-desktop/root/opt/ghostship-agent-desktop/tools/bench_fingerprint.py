#!/usr/bin/env python3
"""Browser realness parity between a candidate Chrome and a control Chrome.

Loads a local page (no external traffic) in a fresh window of each Chrome and
collects the signals sites use to tell a real desktop browser from an
automated or headless one: webdriver, user agent and client hints, screen and
window geometry, focus and visibility, WebGL, canvas and audio hashes, media
devices, permissions, fonts, media queries and more. The candidate passes
when every signal equals the control's, apart from --allow keys (differences
the change intends, e.g. screen size). One one-shot evaluate on our own page;
the Runtime domain is never enabled.

  python3 bench_fingerprint.py --control 9230 --candidate 9231 --allow screen,avail
  python3 bench_fingerprint.py --dump 9222 > baseline.json      # record a known-good image
  python3 bench_fingerprint.py --baseline baseline.json --candidate 9222
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_ws import Cdp  # noqa: E402
import bench_input  # noqa: E402

COLLECT = r"""(async () => {
  const hash = async (s) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
    new TextEncoder().encode(s)))).slice(0, 8).map(b => b.toString(16).padStart(2, '0')).join('');
  const out = {};
  const n = navigator;
  out.webdriver = n.webdriver;
  out.userAgent = n.userAgent;
  out.platform = n.platform;
  out.vendor = n.vendor;
  out.languages = n.languages;
  out.hardwareConcurrency = n.hardwareConcurrency;
  out.deviceMemory = n.deviceMemory;
  out.maxTouchPoints = n.maxTouchPoints;
  out.cookieEnabled = n.cookieEnabled;
  out.pdfViewerEnabled = n.pdfViewerEnabled;
  out.plugins = Array.from(n.plugins || []).map(p => p.name);
  out.mimeTypes = Array.from(n.mimeTypes || []).map(m => m.type);
  try {
    const h = await n.userAgentData.getHighEntropyValues(['architecture', 'bitness', 'model', 'platformVersion',
      'fullVersionList', 'wow64', 'formFactors']);
    out.uaData = {brands: n.userAgentData.brands, mobile: n.userAgentData.mobile, platform: n.userAgentData.platform, ...h};
  } catch (e) { out.uaData = String(e); }
  out.chromeObject = typeof window.chrome === 'object' && Object.keys(window.chrome).sort();
  out.screen = [screen.width, screen.height, screen.colorDepth, screen.pixelDepth];
  out.avail = [screen.availWidth, screen.availHeight, screen.availLeft, screen.availTop];
  out.dpr = devicePixelRatio;
  out.outerMinusInner = [outerWidth - innerWidth, outerHeight - innerHeight];
  out.windowWithinScreen = outerWidth <= screen.width && outerHeight <= screen.height;
  out.visibility = document.visibilityState;
  out.hidden = document.hidden;
  out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  out.locale = Intl.DateTimeFormat().resolvedOptions().locale;
  out.tzOffset = new Date(2026, 0, 1).getTimezoneOffset();
  const mq = q => matchMedia(q).matches;
  out.media = {finePointer: mq('(pointer: fine)'), hover: mq('(hover: hover)'), anyCoarse: mq('(any-pointer: coarse)'),
    dark: mq('(prefers-color-scheme: dark)'), reducedMotion: mq('(prefers-reduced-motion: reduce)'),
    colorGamut: mq('(color-gamut: p3)'), hdr: mq('(dynamic-range: high)'), standalone: mq('(display-mode: standalone)')};
  try {
    const c = document.createElement('canvas');
    const g = c.getContext('webgl');
    const e = g.getExtension('WEBGL_debug_renderer_info');
    out.webgl = {vendor: g.getParameter(e.UNMASKED_VENDOR_WEBGL), renderer: g.getParameter(e.UNMASKED_RENDERER_WEBGL),
      params: await hash(JSON.stringify([g.getParameter(g.MAX_TEXTURE_SIZE), g.getParameter(g.MAX_VIEWPORT_DIMS),
        g.getParameter(g.MAX_RENDERBUFFER_SIZE), g.getSupportedExtensions()]))};
    const g2 = document.createElement('canvas').getContext('webgl2');
    out.webgl2 = !!g2;
  } catch (e) { out.webgl = String(e); }
  try {
    const c = document.createElement('canvas'); c.width = 240; c.height = 60;
    const x = c.getContext('2d');
    x.textBaseline = 'top'; x.font = '16px Arial'; x.fillStyle = '#f60'; x.fillRect(100, 1, 62, 20);
    x.fillStyle = '#069'; x.fillText('Ghostship fp \u{1F600} ⌘', 2, 15);
    x.fillStyle = 'rgba(102,204,0,0.7)'; x.fillText('Ghostship fp', 4, 17);
    out.canvas = await hash(c.toDataURL());
  } catch (e) { out.canvas = String(e); }
  try {
    const ctx = new OfflineAudioContext(1, 5000, 44100);
    const o = ctx.createOscillator(); o.type = 'triangle'; o.frequency.value = 1000;
    const comp = ctx.createDynamicsCompressor(); o.connect(comp); comp.connect(ctx.destination); o.start(0);
    const buf = await ctx.startRendering();
    out.audio = await hash(Array.from(buf.getChannelData(0).slice(4000, 4100)).join(','));
  } catch (e) { out.audio = String(e); }
  try {
    const devices = await n.mediaDevices.enumerateDevices();
    out.mediaDevices = devices.map(d => d.kind).sort();
  } catch (e) { out.mediaDevices = String(e); }
  out.permissions = {};
  for (const name of ['notifications', 'geolocation', 'camera', 'microphone', 'clipboard-read', 'midi']) {
    try { out.permissions[name] = (await n.permissions.query({name})).state; } catch (e) { out.permissions[name] = 'error'; }
  }
  out.notification = typeof Notification === 'function' ? Notification.permission : null;
  const fonts = ['Arial', 'Noto Color Emoji', 'DejaVu Sans', 'Liberation Sans', 'Ubuntu', 'Noto Sans', 'Courier New',
    'Times New Roman', 'Helvetica', 'Roboto', 'Cantarell', 'Segoe UI'];
  await document.fonts.ready;
  out.fonts = fonts.filter(f => document.fonts.check(`12px "${f}"`));
  out.speechVoices = (window.speechSynthesis && speechSynthesis.getVoices().length) || 0;
  out.connection = n.connection ? [n.connection.effectiveType, n.connection.rtt > 0] : null;
  out.storageQuotaGiB = Math.round(((await n.storage.estimate()).quota || 0) / 2 ** 30);
  out.gpu = !!n.gpu;
  out.bluetooth = !!n.bluetooth;
  out.keyboard = !!n.keyboard;
  out.historyLength = history.length;
  return JSON.stringify(out);
})()"""


async def collect(port: int, http_port: int) -> dict:
    cdp = await Cdp.connect(port)
    target = (await cdp.send("Target.createTarget", {"url": f"http://127.0.0.1:{http_port}/?agent=fingerprint",
                                                     "newWindow": True, "background": True}))["targetId"]
    try:
        session = (await cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        await bench_input.wait_loaded(cdp, session)
        await asyncio.sleep(1.0)
        return json.loads(await cdp.evaluate(session, COLLECT, timeout=30))
    finally:
        await cdp.send("Target.closeTarget", {"targetId": target})
        await cdp.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", type=int, help="control Chrome DevTools port")
    parser.add_argument("--baseline", help="control signals saved earlier with --dump (instead of --control)")
    parser.add_argument("--candidate", type=int, help="candidate Chrome DevTools port")
    parser.add_argument("--dump", type=int, metavar="PORT", help="print one Chrome's signals as JSON and exit")
    parser.add_argument("--allow", default="", help="comma-separated signals allowed to differ")
    parser.add_argument("--show", action="store_true", help="print both signal sets")
    args = parser.parse_args()
    http_port = bench_input.serve()
    if args.dump:
        print(json.dumps(asyncio.run(collect(args.dump, http_port)), indent=1, sort_keys=True))
        return 0
    if args.candidate is None or (args.control is None) == (args.baseline is None):
        parser.error("give --candidate and exactly one of --control or --baseline")
    control = (json.load(open(args.baseline, encoding="utf-8")) if args.baseline
               else asyncio.run(collect(args.control, http_port)))
    candidate = asyncio.run(collect(args.candidate, http_port))
    allowed = {key for key in args.allow.split(",") if key}
    differences = {key: {"control": control.get(key), "candidate": candidate.get(key)}
                   for key in sorted(set(control) | set(candidate)) if control.get(key) != candidate.get(key)}
    blocking = {key: value for key, value in differences.items() if key not in allowed}
    # Signals that must hold whatever the control says.
    absolute = {"webdriver": candidate.get("webdriver") is False, "visible": candidate.get("visibility") == "visible",
                "windowWithinScreen": candidate.get("windowWithinScreen") is True,
                "realGpu": "SwiftShader" not in json.dumps(candidate.get("webgl"))
                and "llvmpipe" not in json.dumps(candidate.get("webgl"))}
    report = {"signals": len(candidate), "differences": differences, "blocking": sorted(blocking),
              "absolute": absolute, "pass": not blocking and all(absolute.values())}
    if args.show:
        report["control"], report["candidate"] = control, candidate
    print(json.dumps(report, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
