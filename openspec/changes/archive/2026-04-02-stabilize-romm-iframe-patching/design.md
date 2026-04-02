## Context

`modules/self-hosted/romm.nix` used to patch the active RomM frontend bundle in
`postStart` by replacing one exact minified router hook string. The
April 1, 2026 `rommapp/romm:latest` image updated RomM to 4.8.0 and changed the
bundle shape enough that the patch no longer matched, which broke startup. That
stale rewrite is now gone, and `podman-romm.service` starts cleanly again.

The repo already switched Muximux from the public
`https://romm.ghostship.io` origin to a same-origin `/romm/` reverse proxy.
That removed the Cloudflare/public-origin boundary, but the real Muximux iframe
path on Chrome still does not render the login view correctly. Live debugging
now shows:

- the RomM iframe is same-origin and loads `http://.../romm/`
- the RomM document title reaches `Login`
- the app root stays empty after boot
- the browser console reports `TypeError: Cannot read properties of null
  (reading 'refs')`

The old live notes already showed this secondary runtime failure after
short-circuiting the router `beforeResolve` wait. The change therefore shifts
from “same-origin proxy is enough” to “same-origin proxy remains necessary, and
the remaining iframe-only lifecycle bug should be handled by a proxy-injected
runtime shim instead of editing RomM's served bundle.”

## Goals / Non-Goals

**Goals:**
- Verify the current same-origin `/romm/` behavior without any persistent live
  RomM file edits and capture the remaining iframe-only failure precisely.
- Keep RomM startup free of hashed-bundle rewrites and one-off live file edits.
- Preserve the same-origin Muximux reverse proxy because it still removes the
  Cloudflare/public-origin iframe failure path.
- Inject an iframe-only runtime shim before RomM boots so the mitigation
  survives routine upstream image restarts and frontend rebuilds.
- Keep the validated Muximux embed path declarative in the NixOS module and
  documented for future RomM upgrades.

**Non-Goals:**
- Rework unrelated RomM configuration, secrets, or database wiring.
- Introduce a permanent fork of the RomM image or maintain a custom upstream
  frontend build.
- Solve broader Cloudflare Access policy outside the specific Muximux RomM
  embedding path.
- Guarantee a source-free fix if the remaining runtime failure ultimately
  depends on RomM internals that cannot be neutralized from stable browser
  surfaces.

## Decisions

### 1. Treat the same-origin proxy as necessary but not sufficient
The first step is to keep the existing `/romm/` reverse proxy and verify the
remaining live behavior against that real Muximux path, not against the removed
public-origin embed or a stale local tunnel assumption.

Why:
- The Cloudflare/public-origin issue is already fixed by the existing `/romm/`
  proxy and should not be reintroduced.
- The current problem is now the iframe-only runtime failure after RomM boots.

Alternatives considered:
- Revert to the public RomM hostname and keep debugging there. Rejected because
  it confuses two separate failure classes and reintroduces the known Access
  boundary.

### 2. Prefer an iframe-only runtime shim over any RomM bundle patch
The preferred mitigation is to inject a small runtime shim from the Muximux
proxy into RomM's HTML before the main module loads. The shim should run only
when RomM is framed and should patch stable browser/runtime APIs that differ in
iframe contexts.

Why:
- The remaining failure is now in the framed runtime path after the app loads,
  not in RomM container startup.
- A pre-bootstrap shim can survive frontend rebuilds because it targets browser
  behavior rather than hashed filenames or minified implementation details.
- The shim can be kept declarative in Muximux, which already owns the `/romm/`
  embedding boundary.

Alternatives considered:
- Continue patching the active JS bundle with broader regexes. Rejected because
  it still depends on RomM's compiled output and is exactly the brittle class of
  fix this change is trying to remove.
- Inject the shim by editing RomM `index.html` inside the container. Rejected
  because the correct ownership boundary is Muximux's embed path, not RomM's
  filesystem.
- Pin RomM to an older image. Rejected because the current image is not the
  actual root cause.

### 3. Make the shim target stable browser surfaces and no-op top-level
The injected shim should:

- run only when `window.top !== window.self`
- install before RomM's main module executes
- patch stable browser surfaces such as transition, focus, visibility, or
  closely related iframe lifecycle behavior
- avoid any dependency on RomM's minified symbol names
- leave direct `/romm/` top-level behavior unchanged

Why:
- This is the only credible path to a runtime-only fix that can survive routine
  upstream frontend updates.
- A top-level no-op boundary keeps the shim from changing direct RomM behavior,
  which remains a useful diagnostic split.

### 4. Keep host-side validation split between direct `/romm/` and `/#RomM`
The host workflow should distinguish:

- RomM startup failures
- direct top-level RomM behavior at `/romm/`
- Muximux iframe behavior at `/#RomM`
- shim-injection failures

Why:
- The current blank-login symptom appears only in the iframe path even though
  the same document loads under the same origin.
- Keeping those paths separate is the only way to tell whether the shim fixes
  iframe lifecycle differences or merely shifts the failure elsewhere.

## Risks / Trade-offs

- [The remaining failure may still depend on RomM internals] -> Treat the shim
  as successful only if the login DOM actually renders; do not accept a title
  change alone as success.
- [A shim can still be too broad if it patches core browser APIs globally] ->
  Scope every override to framed loads and keep the patch surface minimal.
- [RomM may still emit root-relative asset or API paths under `/romm/`] ->
  Keep proxying `/romm/`, `/assets/`, and `/api/` through Muximux as already
  validated live.
- [The Muximux proxy could drift from the runtime-generated default config] ->
  Install the managed vhost and shim asset before container start so the proxy
  path is declarative.
- [Browser cache may retain an earlier failing asset path] -> Let Muximux own
  the shim cache-bust string and avoid ad hoc cache-busting on RomM's hashed
  bundle names.

## Migration Plan

1. Reproduce the current direct `/romm/` and iframe `/#RomM` behavior on
   `chill-penguin`, including the live console/runtime failure.
2. Implement a managed iframe-only shim asset and HTML injection path in
   `modules/self-hosted/muximux.nix`.
3. Rebuild the host, remove the temporary live RomM bundle edits, and verify
   whether the shim restores the real Muximux login render without changing
   direct `/romm/` behavior.
4. Roll back by switching to the prior NixOS generation if the shim regresses
   Muximux or RomM availability.

## Open Questions

- Which exact browser-side invariant needs to be normalized for the current
  `null.refs` login failure: transition state, focus timing, visibility timing,
  or another framed lifecycle assumption?
- Does any other Muximux-managed service rely on root `/assets/` or `/api/`
  paths that would conflict with the RomM proxy locations?
