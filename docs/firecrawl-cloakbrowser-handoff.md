# Firecrawl CloakBrowser Image Handoff

Firecrawl should consume the shared Ghostship CloakBrowser substrate through its existing Playwright service image instead of through a standalone browser manager or a changedetection-style plugin.

## Required contract

- Keep Firecrawl's `PLAYWRIGHT_MICROSERVICE_URL` contract unchanged.
- Build a Firecrawl Playwright-service image that embeds the same CloakBrowser binary contract used by `pricebuddy-scraper` and `changedetection`.
- Export `CLOAKBROWSER_BINARY_PATH` inside that image.
- Launch Playwright through the CloakBrowser wrapper with `humanize=True`.
- Keep `geoip` off by default.
- Do not add a remote CDP manager dependency.

## Build shape

1. Start from the upstream Firecrawl Playwright service image or Docker context.
2. Install the shared CloakBrowser package and pre-download the binary during image build.
3. Normalize the binary to the stable in-image path referenced by `CLOAKBROWSER_BINARY_PATH`.
4. Patch only the Playwright launch seam so it uses the embedded browser contract.
5. Leave the Firecrawl API image and its HTTP contract untouched unless upstream changes force a coordinated update.

## Launch requirements

- Use the CloakBrowser Playwright wrapper, not raw `chromium.launch()` with a stock executable.
- Enable `humanize=True`.
- Keep default stealth args enabled.
- Keep proxy wiring, if present, inside the Playwright service boundary.
- Do not enable `geoip` unless Firecrawl later adopts a deliberate proxy-aware locale/timezone policy.

## Acceptance checks

- The Playwright service image starts without downloading a browser at runtime.
- `CLOAKBROWSER_BINARY_PATH` exists in the final image.
- Firecrawl continues to speak to the Playwright service through `PLAYWRIGHT_MICROSERVICE_URL`.
- JavaScript-rendered page fetches still work.
- Screenshot flows still work.
- No remote CDP manager is introduced.
