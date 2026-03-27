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

Correction:
- `apps.ghostship.io` and `romm.ghostship.io` are same-site subdomains, not cross-site. RomM cookies remain owned by `romm.ghostship.io` unless they explicitly set `Domain=.ghostship.io`, but `SameSite=Strict` alone should not block them between these two hosts. Keep cookie/header handling in scope, but do not treat `SameSite=Strict` as a proven root cause by itself.

## 2026-03-27: RomM restart loop was caused by a broken generated Nginx template

Checks performed:
- Opened the live `/nix/store/.../podman-romm-pre-start/bin/podman-romm-pre-start` script on the host
- Confirmed it writes `listen ${ROMM_PORT};`, `${IPV6_LISTEN}`, and `alias "${ROMM_BASE_PATH}/library/";` inside a shell heredoc
- Confirmed systemd does not set those shell variables for the preStart script
- Observed the resulting live template collapse to `listen ;` and `alias "/library/";`
- Confirmed nginx then exited with `invalid number of arguments in "listen" directive`

Manual recovery for testing:
- Patched `/etc/nginx/conf.d/default.conf` inside the running `romm` container to use `listen 8080;`
- Patched the internal alias to `"/romm/library/"`
- Inserted `proxy_cookie_flags romm_session secure samesite=none;` and `proxy_cookie_flags romm_csrftoken secure samesite=none;`
- Validated with `nginx -t`
- Started nginx manually in the container and confirmed the container returned to `healthy`
- Verified `GET /api/heartbeat` now returns `set-cookie: romm_csrftoken=...; Path=/; SameSite=None; Secure`

Outcome:
- The iframe still crashed after the live cookie rewrite, so cookie attributes are not the sole cause of the embedded failure.

## 2026-03-27: RomM iframe crash is triggered by app mount, not startup fetches

Checks performed:
- Created `iframe-shell.html` from the real RomM `index.html` with the main JS bundle removed
- Confirmed `romm-shell-test.html` frames that shell successfully
- Created a `no-boot` bundle variant that loads the real bundle but removes the final `RG()` call
- Confirmed the `no-boot` iframe does not crash
- Split `RG()` into two tests:
  - `premount`: `ku(E5)`, `yG(e)`, `await CG()`, `e.use(Ll)`, no `mount()`
  - `mount-no-cg`: `ku(E5)`, `yG(e)`, `e.use(Ll)`, `e.mount("#app")`, no `CG()`
- Observed `premount` works and `mount-no-cg` crashes

Conclusion:
- The iframe crash is not caused by script download, the shell HTML, manifests, CSS, or the async `CG()` startup fetches.
- The trigger is in the Vue mount/render path: the root RomM component tree, router initial route render, or something mounted immediately after `e.mount("#app")`.

## 2026-03-27: Disabling the router's View Transition hook did not stop the crash

Checks performed:
- Located the live router hook: `Ll.beforeResolve(async()=>{ await LU().captured })`
- Confirmed `LU()` calls `document.startViewTransition()` when that API is available
- Built an iframe-only test bundle variant that short-circuits `LU()` in framed loads with `if(window.top!==window.self)return n;`
- Confirmed `romm-novtiframe-test.html` still crashes in the iframe

Conclusion:
- Chrome's View Transition API is not the sole trigger for the RomM iframe crash.
- The failure remains in the mount/render path after the router plugin is installed, so the next split should isolate the root RomM component tree from the first routed component render.

## 2026-03-27: The crash begins when the router renders a real route component

Checks performed:
- Confirmed `romm-mountstub-test.html` does not crash when Vue mounts a trivial component after `yG(e)`
- Confirmed `romm-rootnorouter-test.html` does not crash when the compiled `RomM` root component mounts without `e.use(Ll)`

Conclusion:
- Vue mount infrastructure is not the trigger.
- The compiled `RomM` root component is not the trigger by itself.
- The remaining failure surface is the first real route component render after the router is installed.

## 2026-03-27: The original Setup component crashes only when rendered

Checks performed:
- Confirmed `/login` works while `/setup` crashes after isolating the auth-side route space
- Created a fresh `Setup-eval-original.js` asset URL and an iframe page that only imports it as a module
- Confirmed `romm-setup-import-test.html` reports `setup chunk import ok`
- Created a fresh `index-setupmount.js` bootstrap that imports the original `Setup` component and mounts it directly with `yG(e)` but without the router
- Confirmed `romm-setup-direct-mount-test.html` still crashes

Conclusion:
- The `Setup` module can be evaluated safely; the crash is not caused by loading the file.
- Rendering the original `Setup` component is enough to trigger the iframe crash.
- The next split should isolate the `Setup` render tree itself (for example the stepper/window shell versus the content inside each step).

## 2026-03-27: Setup shell/window tests pass; the crash is inside the real pane content

Checks performed:
- Created direct-mount Setup variants that render only the stepper header shell
- Confirmed `romm-setup-stepper-test.html` does not crash
- Created a second variant that renders the stepper header plus empty `VStepperWindow` panes
- Confirmed `romm-setup-stepperwindow-test.html` does not crash
- Confirmed simplified Setup variants with a trivial render tree both with and without `We()` (`romm-setup-min-test.html` and `romm-setup-minwe-test.html`) do not crash

Conclusion:
- The stepper shell itself is not the trigger.
- The empty stepper-window layer is not the trigger.
- `We()` / the mounted library-info fetch is not the trigger by itself.
- The remaining suspect surface is the actual rendered pane content inside Setup.

## 2026-03-27: Only Setup pane 3 crashes in the iframe

Checks performed:
- Created three direct-mount Setup variants that each keep exactly one real pane and replace the other two panes with inert placeholders
- Confirmed `romm-setup-pane1-test.html` does not crash
- Confirmed `romm-setup-pane2-test.html` does not crash
- Confirmed `romm-setup-pane3-test.html` still crashes

Conclusion:
- The library-structure pane is not the trigger.
- The admin-user pane is not the trigger.
- The metadata-source pane is sufficient to trigger the iframe crash on its own.
- The next split should isolate the metadata-source row components, especially `VListItem`, `VAvatar`, `VImg`, and the append checkmark span rendered in pane 3.

## 2026-03-27: A single original metadata row is enough to crash

Checks performed:
- Created `romm-setup-pane3-oneitem-test.html`, which keeps only the first metadata-source row but preserves the original `VListItem` with both prepend and append slots
- Confirmed that `romm-setup-pane3-oneitem-test.html` still crashes

Conclusion:
- The crash does not require list repetition across many metadata rows.
- One original pane-3 row is enough to trigger the iframe crash.
- The remaining decision point is whether the `VListItem` implementation is required, or whether the same composed row shape also crashes without `VListItem`.

## 2026-03-27: Plain rows work; the crash follows Vuetify `VListItem`

Checks performed:
- Created `romm-setup-pane3-manualrows-test.html`, which renders the same avatar/image, title text, subtitle text, and status glyphs as plain `div` rows instead of `VListItem`
- Confirmed `romm-setup-pane3-manualrows-test.html` does not crash

Conclusion:
- The image assets and glyphs are not sufficient to trigger the crash on their own.
- The remaining suspect surface is Vuetify `VListItem` when both prepend and append slots are active in the same row.

## 2026-03-27: The single-row crash requires the original subtitle plus both original slots

Checks performed:
- Created `romm-setup-pane3-vlimin-test.html`, a single-row `VListItem` with both prepend and append slots but only trivial text payload in those slots
- Confirmed `romm-setup-pane3-vlimin-test.html` does not crash
- Created `romm-setup-pane3-orignosub-test.html`, a single-row `VListItem` with the original prepend image/avatar and original append status glyph but no subtitle
- Confirmed `romm-setup-pane3-orignosub-test.html` does not crash

Conclusion:
- `VListItem` with both slots is not sufficient by itself.
- The original prepend image/avatar plus original append status glyph is not sufficient by itself.
- The remaining failing combination is: original subtitle + original prepend slot + original append slot on the same `VListItem`.

## 2026-03-27: Fresh metadata-row retest confirms the row bug, and patched full Setup works when mounted directly

Checks performed:
- Published fresh filename retests for the crashing single original metadata row and the working manual-row equivalent
- Confirmed `romm-rowretest-orig-test.html` still crashes
- Confirmed `romm-rowretest-manual-test.html` still works
- Published a fresh direct-mount page that imports the patched full `Setup-livefix.js`
- Confirmed `romm-setup-direct-livefix-test.html` works

Conclusion:
- The pane-3 metadata row bug is real and reproducible with fresh filenames; it is not a cache artifact.
- Replacing the metadata rows with the safe manual-row implementation is sufficient for the full `Setup` component when mounted directly.
- The remaining crash on the routed `/setup` page comes from an additional trigger in the real router/auth startup path, not from stale caching of the old Setup chunk.
