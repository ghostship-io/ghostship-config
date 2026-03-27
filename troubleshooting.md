# Troubleshooting Log

## 2026-03-27: RomM iframe blocked by Cloudflare Access

Symptoms:
- `https://romm.ghostship.io` loaded in the browser iframe from `https://apps.ghostship.io` failed even after allowing the app origin in the iframe CSP.

Checks performed:
- SSH into `chill-penguin-root`
- Verified `podman ps` shows `romm` healthy
- Verified `podman exec romm curl -skI http://127.0.0.1:8080/` returns `200 OK`
- Verified `podman run --network container:cloudflared curlimages/curl:8.10.1 -skI http://romm:8080/` returns `200 OK`
- Verified `curl -skI https://romm.ghostship.io/` returns a `302` to Cloudflare Access login
- Verified the final Access login response sends `X-Frame-Options: DENY` and `Content-Security-Policy: frame-ancestors 'none'`

Conclusion:
- The RomM container is not the blocker.
- Cloudflare Access is the blocker.
- Fix requires bypassing/unprotecting `romm.ghostship.io` for iframe use, or ensuring the browser already has a valid Access session before loading the iframe.

## 2026-03-27: Portal manifest blocked in iframe

Symptoms:
- Chrome console showed repeated sandbox warnings: `allow-scripts` + `allow-same-origin`.
- The fatal browser error was `STATUS_BREAKPOINT`.
- The console also showed a failed fetch to `https://apps.ghostship.io/images/favicon/manifest.json?v=...`.

Checks performed:
- The manifest request redirected to `stormeagle.cloudflareaccess.com/cdn-cgi/access/login/apps.ghostship.io...`
- That redirected response was then blocked by CORS because it did not include `Access-Control-Allow-Origin`

Conclusion:
- The iframe failure is not only about RomM headers.
- The portal at `apps.ghostship.io` is also loading a protected asset through Access in a way Chrome will not tolerate inside the embed context.
- The next server-side fix should target the portal asset path or Access policy for `apps.ghostship.io`, not RomM alone.

Follow-up:
- Removing the Muximux manifest link did not stop the `STATUS_BREAKPOINT` crash, so the manifest fetch was not the root cause.

## 2026-03-27: RomM shell exposes PWA/autofocus behavior

Checks performed:
- Fetched the live RomM HTML directly from the container
- Confirmed the shell emits both `<link rel="manifest" href="/site.webmanifest" />` and `<link rel="manifest" href="/manifest.webmanifest">`
- Confirmed the JS bundle references `autofocus`, `localStorage`, and a `register(` call, but no `navigator.serviceWorker`
- Confirmed the manifest URLs currently fall back to `index.html` on the local Nginx origin

Implication:
- The next RomM-side experiment should target the app shell itself, not Muximux. A focused HTML patch that suppresses manifest loading in iframe context is a plausible testable change.

## 2026-03-27: RomM manifest suppression failed to stop iframe crash

Tested change:
- Added iframe-only `manifest-src 'none'` to RomM's CSP

Outcome:
- The iframe still crashed with `STATUS_BREAKPOINT`

Implication:
- The manifest fetch path is not the trigger.
- The next minimal test should suppress autofocus in iframe context or otherwise avoid the initial focus behavior during startup.

## 2026-03-27: Live RomM iframe focus guard injected

Checks performed:
- Verified the running container was still serving the old Nginx template, so the earlier repo-only CSP edit had not been deployed
- Verified RomM serves a real PWA surface: `/manifest.webmanifest`, `/site.webmanifest`, `/sw.js`, and `workbox-*.js`
- Injected a reversible script directly into the live `/var/www/html/index.html` inside the `romm` container

Live patch behavior:
- Only activates when `window.top !== window.self`
- Removes `autofocus` attributes after `DOMContentLoaded`
- Blocks programmatic `HTMLElement.prototype.focus()` until the first user pointer or keyboard interaction

Purpose:
- Test whether RomM's startup focus behavior is the frame-only crash trigger while leaving standalone behavior unchanged.

## 2026-03-27: RomM main document is frame-allowed, but auth cookies are not iframe-safe

Checks performed:
- Reviewed a live browser header capture for `https://romm.ghostship.io/` inside the iframe
- Confirmed the response includes `Content-Security-Policy: frame-ancestors https://apps.ghostship.io 'self';`
- Confirmed the response includes `Cross-Origin-Embedder-Policy: unsafe-none` and `Cross-Origin-Opener-Policy: unsafe-none`
- Confirmed the running container is healthy again with `podman ps`
- Re-read the live `/backend/main.py` inside the running container and confirmed it still uses `same_site="lax" if OIDC_ENABLED else "strict"` plus `https_only=False`

Conclusion:
- The top-level RomM document is not being blocked by the usual iframe headers.
- The remaining header-level issue is the RomM auth cookie policy itself.
- Because `apps.ghostship.io` embedding `romm.ghostship.io` is cross-site, `SameSite=Strict` prevents `romm_session` from being sent in the iframe even though the standalone tab works.
- The next durable fix should be RomM emitting `SameSite=None; Secure` for its session cookie, and likely doing the same for any CSRF cookie used by authenticated API requests.
