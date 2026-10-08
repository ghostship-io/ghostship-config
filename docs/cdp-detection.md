# CDP detection testing

Home Depot's Akamai/PerimeterX protection blocks Playwright-driven sessions
but allows manual browsing. This document records the isolation experiments
that found the trigger, the driver comparison, and the per-site driver
preference. The tooling lives in
`containers/agent-desktop/root/opt/ghostship-agent-desktop/tools/` and ships
in the desktop image.

## Method

- Standalone, dependency-free CDP client (`tools/cdp_client.py`).
- Local detector page (`tools/diag.html`) reproducing
  deviceandbrowserinfo's `cdpCheck1`: it wraps `Error.prepareStackTrace`, logs
  an `Error`, and reports whether the wrapper fired — which happens when a
  CDP client serializes the console argument.
- Harness (`tools/run_cdp_matrix.py`) serving the page, launching one Chrome
  per variant from a closed seed profile, running exactly one operation set,
  and recording the page's own reports plus Pelorus screenshots. No second
  CDP connection is used for observation.
- Retailer runner (`tools/run_retailer.py`) performs the same browsing
  journey per driver with evidence screenshots.

All runs: Chrome 155.0.8059.39, aarch64, Wayland, 1600x900, egress
`72.235.23.7` (Hawaiian Telcom), profiles cloned from the same closed seed.

## Phase 1 — what triggers detection

| Variant | Operation | Detected |
| --- | --- | --- |
| A0 | no DevTools port | no |
| A1 | port open, no connection | no |
| A2 | HTTP `/json/version` + `/json/list` | no |
| A3 | browser WS + `Browser.getVersion` | no |
| A4 | `Target.getTargets` | no |
| A5 | page WS connect only | no |
| A6 | `Target.attachToTarget` | no |
| A7 | attach + `Page.enable` | no |
| A8 | attach + `Network.enable` | no |
| A9 | attach + `DOM.enable` | no |
| A10 | attach + `Runtime.evaluate` (no enable) | no |
| A11 | attach + `Accessibility.getFullAXTree` | no |
| A12 | attach + `Input.dispatchMouseEvent` | no |
| A13 | attach + `Runtime.enable` | **yes** |
| B7P | page WS + `Page.enable` | no |

**The single trigger is `Runtime.enable`.** Discovery, attachment, Page,
Network, DOM, Accessibility, Input and one-shot evaluation are all clean.
The detection fires while the session is enabled and clears after detach.

## Phase 2 — scope and timing

- **B2 process isolation**: verified. A Chrome with `Runtime.enable` attached
  is detected while a second, untouched Chrome on the same desktop stays
  clean.
- **B3 attach after load**: covered by every A6–A13 run — the page is loaded
  before the operations; only A13 flips.
- **B4 detach recovery**: verified. A13 reports detection only during the
  enabled window (4 of 11 reports) and returns to baseline afterwards.
- **B7 attachment scope**: page-level WS (`Page.enable`) and browser-level
  attach (`Page.enable`) behave identically (clean).
- B1/B5/B6 (native-input tab/navigation variants) were not run; the trigger
  is a per-session command, so they cannot change the outcome.

## Phase 3 — driver comparison

| Candidate | Detector | Notes |
| --- | --- | --- |
| C1 raw minimal CDP (attach, Page, evaluate, AXTree, Input) | clean | functional: read page text |
| C2 Bladebro `rb attach` (`--port`) | clean | `see content` works |
| C4 Bladebro profile mode (`rb profile`, own launch) | clean | `nav` works |
| C5 Playwright MCP Chrome extension | not promoted | Playwright-based; enables Runtime |
| C6 Chrome DevTools MCP | not promoted | broad domain set including Runtime |
| Chrome extension transport (no CDP) | unavailable | branded Chrome 155 ignores `--load-extension`; a policy-installed CRX would be required |

Bladebro's real-browser lane does not call `Runtime.enable`, so it passes the
same detector as the no-CDP baseline. Playwright enables Runtime and is
detected. C5/C6 were not run: both are Runtime-enabling clients and therefore
fail the Phase 1 detector by construction.

### Chrome extension transport

An unpacked MV3 extension (`tools/ext/`, driven over the local command
channel in `tools/run_extension.py`) was evaluated as the non-CDP
alternative. **Branded Google Chrome 155 ignores `--load-extension` and
`--disable-extensions-except`**: the extension never starts, so the transport
is unavailable without an enterprise policy and a hosted CRX. Given the
constraint to preserve official Google Chrome and avoid permanent launcher
changes, native desktop control (Pelorus/Selkies) remains the non-CDP
fallback, and Bladebro attach the validated automation path.

## Phase 4 — Home Depot journey

Same journey (home → search → extract → product → reload) per driver on a
seasoned profile clone. A denial means the error page or a 403; candidates
are not retried.

| Driver | Home | Search | Products | Product page | Reload | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| no-CDP control | ok | grid renders (225 results) | grid visible | screenshot only | — | works |
| Bladebro `nav --port` | ok | redirected browse page | 12 distinct products, prices | loaded | ok | **works** |
| raw minimal CDP | ok | browse page | 15 distinct products, prices | loaded | ok | **works** |

The hardened runner requires live extracted product links (never a fallback),
distinct products, prices, complete pages and a successful reload, and
classifies 403s, challenges and incomplete pages explicitly.

### Retailer matrix (Bladebro attach, 2026-10-08)

| Site | Result | Distinct products | Prices |
| --- | --- | --- | --- |
| Home Depot | ok | 15 | 13 |
| Lowe's | ok | 24 | 61 |
| Amazon | ok | 122 | 198 |
| Walmart | ok | 97 | 266 |
| Target | ok | 74 | 66 |

No challenge, 403 or error markers on any of the five.

`_abck` remained present; success was judged from rendered content only.
deviceandbrowserinfo under a Bladebro attach reports **"You are human!"**
(`isBot: false`, `isPlaywright: false`) exactly as without CDP.

## Recommended configuration

1. **Agents**: use Bladebro's real-browser lane attached to the existing
   Chrome (`bladebro-agent`, `--port 9222`) — validated on Home Depot and
   Lowe's. Do not attach Playwright or any client that enables `Runtime`.
2. **Direct CDP scripts**: restrict to the clean operation set — discovery,
   attach, Page, one-shot `Runtime.evaluate`, Accessibility, Input. Never
   call `Runtime.enable` against bot-managed pages.
3. **Native desktop control**: Pelorus compositor input remains the fallback
   for sites that still challenge, and for manual human work through Selkies.
4. **Do not** use Playwright on Home Depot or other Akamai/PerimeterX sites.

## Per-site driver preference

| Site | CDP | Notes |
| --- | --- | --- |
| Home Depot | Bladebro attach or raw clean CDP | Playwright/Runtime blocked |
| Lowe's, Amazon, Walmart, Target | Bladebro attach | validated 2026-10-08 |
| Default | validate with the matrix | fall back to Pelorus/manual |

## Upgrades and rollback

Known-good pins live in `containers/agent-desktop/Containerfile`: Google
Chrome `155.0.8059.39-1` (SHA-256 per architecture), Bladebro `4.2.2`
(SHA-256 per architecture), and the base image digest. The current pins are
the validated set recorded above.

Upgrade procedure:

1. Bump the pin and checksums in the Containerfile.
2. Rebuild the image and restart the desktop container.
3. Run `tools/check_cdp_regression.py` inside the container; it must pass.
4. Run `tools/run_retailer.py --driver bladebro` on a seasoned profile and
   confirm `journey_ok: true` for Home Depot, then spot-check Lowe's.
5. Promote only when both pass.

Rollback: revert the pin commit and rebuild. Image tags are
content-addressed, so the previous image returns unchanged, and
`storage-health` keeps recent tags for roughly a week. Profiles and
authentication are untouched by either direction.

## Regression

Run inside the desktop container:

```sh
python3 /opt/ghostship-agent-desktop/tools/check_cdp_regression.py
```

It asserts A6/A10/C2 stay clean and A13 still detects, and fails on missing
results, fewer than five page samples, Chrome startup failures, command
errors or unsuccessful commands. The tools load the desktop session
environment themselves, so a timer or `podman exec` can run them. The
retailer runner requires live extracted product links (never a fallback),
distinct products, prices, complete pages and a successful reload, and
classifies 403s, challenges and incomplete pages explicitly. Re-run the
regression after every Bladebro or Chrome update; `tools/run_cdp_matrix.py`
reproduces the full matrix and `tools/run_retailer.py` the retailer journey.
