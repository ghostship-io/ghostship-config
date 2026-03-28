# RomM Iframe Debug Notes

Date: 2026-03-27

## Goal

Investigate why `https://romm.ghostship.io` works standalone but crashes or fails when embedded in an iframe from `https://apps.ghostship.io`.

## Environment

- Parent app: `https://apps.ghostship.io`
- Embedded app: `https://romm.ghostship.io`
- Server: `chill-penguin-root`
- Runtime: `podman` container named `romm`

## Server State Confirmed Early

- The `romm` container was healthy.
- RomM answered locally on `http://127.0.0.1:8080/`.
- RomM also answered from the cloudflared network namespace.
- The public site was reachable through Cloudflare.

## Public Header Findings

- The main RomM document was already frame-allowed:
  - `Content-Security-Policy: frame-ancestors https://apps.ghostship.io 'self'`
- `Cross-Origin-Embedder-Policy` and `Cross-Origin-Opener-Policy` were already `unsafe-none`.
- No main-document `X-Frame-Options` blocker was identified in the response the user captured.

Conclusion:

- The top-level iframe refusal was not caused by the obvious document framing headers.

## Cloudflare / Browser Findings

- A Cloudflare Access redirect to the login flow was observed for some requests earlier in the investigation.
- A separate parent-app console error showed a manifest request on `apps.ghostship.io` getting redirected to Cloudflare Access and then blocked by CORS.
- That manifest/CORS path was a real error in the portal context, but removing it did not fix the RomM iframe crash.
- The user also observed Chromium renderer crashes with `STATUS_BREAKPOINT`, which indicates a browser-side crash path, not a normal CSP/XFO block page.

## RomM Cookie / Auth Findings

- RomM cookies were manually rewritten in the running container to:
  - `SameSite=None`
  - `Secure`
- This was verified at least for `romm_csrftoken`.
- The iframe problem persisted after that change.

Conclusion:

- Cookie attributes alone were not the full explanation for the crash path.

## Important Config Bug Found In The Repo

The repo currently contains a real RomM nginx template bug in `modules/self-hosted/romm.nix`:

- generated nginx config relies on shell-expanded values like:
  - `${ROMM_PORT}`
  - `${IPV6_LISTEN}`
  - `${ROMM_BASE_PATH}`
- under systemd those variables are unset in the generated file path that was inspected
- that produced broken live config fragments like:
  - `listen ;`
  - `alias "/library/";`

Manual recovery inside the running container was required to keep RomM healthy:

- `listen 8080;`
- `alias "/romm/library/";`

Implication:

- A blind RomM container restart was unsafe during debugging because it risked falling back to the broken generated nginx config.

## Heartbeat Finding That Invalidated Earlier Assumptions

Live heartbeat from inside the container:

- `SYSTEM.SHOW_SETUP_WIZARD = false`

Implication:

- In the real app, `/setup` does not stay on the Setup wizard.
- The full router guard redirects `/setup` to:
  - `login` when no current user is available
  - `home` when a current user exists

This means earlier "routed `/setup`" crash results were ambiguous unless the actual post-guard route was confirmed.

## Frontend Isolation Work

### Clean findings from the main bundle itself

These tests did not depend on route chunks:

- HTML shell without the main JS bundle worked.
- Loading the real main bundle without calling its boot function worked.
- Running app setup without mount worked.
- A stub Vue app mounted successfully.
- The compiled RomM root component without the router mounted successfully.

Conclusion:

- The failure requires routed render behavior, not just loading the JS bundle.

### Setup-route-specific work

While investigating the Setup wizard route directly, a separate real bug was found:

- the original metadata-source row in Setup pane 3 could reproduce a bad iframe path
- a manual simplified row replacement did not
- a patched full Setup chunk using the safe manual rows worked when mounted directly

Conclusion:

- There is a real Setup metadata-row rendering bug in iframe context.
- However, because `SHOW_SETUP_WIZARD = false`, that bug is not enough by itself to explain the real production `/setup` iframe path.

## Major Test-Harness Correction

Late in the investigation, a critical contamination issue was identified:

- route chunks like:
  - `Auth-DEfpmLbn.js`
  - `Login-CnAfCT08.js`
  - `Main-CyWiqIVJ.js`
  - `Home-CcwY76Xg.js`
  - `Setup-rt7B6UJc.js`
- all import `./index-C1YMu947.js` for shared runtime helpers
- that main bundle contains a top-level `RG()` boot call

Implication:

- Importing one of those route chunks in an ad-hoc test also boots the original app in parallel.
- Many chunk-level tests run during this session were therefore not clean isolates.

This was the last major finding before cleanup started.

## Where The Investigation Ended

At cleanup time, the best current model was:

- the iframe problem is in RomM frontend behavior, not container reachability
- the obvious top-level frame headers were not the blocker
- one real Setup-specific rendering bug exists
- but the main unresolved production iframe crash still needed clean, no-boot route testing to distinguish:
  - authenticated `Main -> Home` path
  - unauthenticated `Auth -> Login` path
  - or another full-router-only behavior

## Live Debug Artifacts Created During Investigation

The session created many temporary files in:

- `romm:/var/www/html/`
- `romm:/var/www/html/assets/`
- `/srv/apps/muximux/www/muximux/`

These included:

- many `iframe-*.html` test pages
- many `romm-*-test.html` wrapper pages
- patched and alternate JS bundles such as:
  - `Setup-livefix.js`
  - `index-*`
  - `Auth-*`
  - clean/no-boot runtime experiments

Cleanup was requested after this document was written.

## Recommended Resume Point

If work resumes, start from a clean server and use a no-boot runtime harness first.

Recommended next order:

1. Create one clean no-boot runtime copy of `index-C1YMu947.js`.
2. Patch only the needed route chunks to import that runtime copy.
3. Re-run exactly two clean tests:
   - authenticated `Main -> Home`
   - unauthenticated `Auth -> Login`
4. Only after that, resume route/component-level narrowing.

## 2026-03-28 Live Host-Port Follow-Up

A direct live-host test on `chill-penguin` settled the current unauthenticated case.

### What changed for the live test

- `podman-romm.service` was temporarily overridden on the host to publish `8080` as host port `18080`
- the public Cloudflare-protected hostname was bypassed by testing `http://192.168.200.82:18080/`
- a same-origin parent probe page was added in the RomM container to load child pages in a real iframe and verify whether the browser session stayed queryable afterward

### Definitive A/B result

- stock child page: `/login?next=/`
  - after the iframe loaded, `agent-browser --session stock-ab get title` timed out after 6 seconds (`EXIT:124`)
- patched stock-bundle child page: `/iframe-login-noresolve.html`
  - this is the same live stock bundle except `Ll.beforeResolve(async()=>{await LU().captured})` was changed to a no-op
  - after the iframe loaded, `agent-browser --session noresolve get title` returned immediately (`EXIT:0`)

### Conclusion

For the current live unauthenticated iframe path, the crash trigger is the real router `beforeResolve` hook:

- `Ll.beforeResolve(async () => { await LU().captured; })`
- `LU()` calls `document.startViewTransition()` when available

Disabling only that hook on the live stock bundle stops the iframe wedge. That rules out framing headers, Cloudflare, host-port exposure, cookies, `CG()`, and the login component by itself as the primary trigger for the current `/login` iframe crash.

### Caveat

The `noresolve` variant surfaced a non-fatal runtime error:

- `TypeError: Cannot read properties of null (reading 'refs')`

So the deeper bug likely sits inside the same navigation / transition path, but the empirically proven trigger for the actual iframe crash is the `beforeResolve -> LU().captured -> document.startViewTransition()` path.

### Live manual fix tests

Two live follow-up patches were tested directly in the running RomM container:

1. `index.html` preload shim
   - injected an iframe-only script before the stock module entry
   - attempted to undefine `document.startViewTransition`
   - result: **did not fix** the live stock `/login?next=/` iframe wedge

2. direct stock-bundle swap
   - restored normal `index.html`
   - replaced `/var/www/html/assets/index-C1YMu947.js` with the `beforeResolve(async()=>{})` variant
   - result: **worked**
   - stock iframe probe stayed responsive
   - top-level `http://192.168.200.82:18080/login?next=/` still loaded normally with title `Login`

Current live-testing conclusion:

- the reliable live mitigation is to remove the real router `beforeResolve` wait from the served bundle
- the attempted iframe-only preload shim is not sufficient on its own

## 2026-03-28 Muximux And Cache Follow-Up

A disposable Muximux instance was exposed on `http://192.168.200.82:18081/` and pointed directly at the live host-published RomM port:

- Muximux test parent: `http://192.168.200.82:18081/`
- RomM child target: `http://192.168.200.82:18080/`

`agent-browser` loaded the Muximux page, clicked the `RomM` tile, and RomM's login form rendered inside the iframe successfully. The page title remained responsive as `RomM - ghostship.io`.

Conclusion:

- Muximux itself is not the crash trigger.
- The remaining broken behavior on `https://romm.ghostship.io` is consistent with public-origin cache state rather than a generic RomM-in-Muximux embed bug.

## 2026-03-28 Persistent Hook Plan

The repo now carries a persistent `systemd.services.podman-romm.postStart` hook in `modules/self-hosted/romm.nix` that:

- waits for the running container to expose `/var/www/html/index.html`
- locates the active hashed `index-*.js` bundle from `index.html`
- rewrites `Ll.beforeResolve(async()=>{await LU().captured})` to `Ll.beforeResolve(async()=>{})`
- removes the temporary iframe/debug files created during this investigation

Important implementation detail:

- the hook must use `podman exec -u 0`
- some live debug files were root-owned inside the container, so cleanup fails under the normal `3000:3000` RomM runtime user
