## Context

`modules/self-hosted/romm.nix` used to patch the active RomM frontend bundle in
`postStart` by replacing one exact minified router hook string. The
April 1, 2026 `rommapp/romm:latest` image updated RomM to 4.8.0 and changed the
bundle shape enough that the patch no longer matched, which broke startup. Live
validation on `chill-penguin` showed that the upstream image itself starts
cleanly and still renders in a same-origin iframe without any RomM-side patch.

The remaining failure path is specific to Muximux embedding the public
`https://romm.ghostship.io` origin, which sits behind Cloudflare Access and is
not a stable iframe target. This change therefore affects the server-host
Muximux and RomM workflow on `chill-penguin`, and it needs a host-side
validation path because the bug only exists in the live Muximux-to-RomM
embedding path.

## Goals / Non-Goals

**Goals:**
- Verify the current RomM image behavior without the repo patch and determine
  whether iframe navigation still crashes or otherwise fails.
- Ensure RomM startup does not fail merely because a frontend bundle hash or
  minified string changed upstream.
- Replace the public-origin Muximux embed with a same-origin reverse proxy that
  survives routine upstream image restarts and Podman IP churn.
- Keep the validated Muximux embed path declarative in the NixOS module and
  documented for future RomM upgrades.

**Non-Goals:**
- Rework unrelated RomM configuration, secrets, or database wiring.
- Introduce a permanent fork of the RomM image or maintain a custom upstream
  frontend build.
- Solve broader Cloudflare Access policy outside the specific Muximux RomM
  embedding path.

## Decisions

### 1. Validate the live image without the patch before changing mitigation
The first step is to disable or bypass the current `postStart` patch on the
host, restart RomM, and reproduce the iframe flow against the unmodified 4.8.0
image.

Why:
- The current service failure proved only that the patch was stale, not that
  the upstream image still needed the workaround.
- If upstream already fixed the bug, the durable solution is to remove the
  patch entirely.

Alternatives considered:
- Keep updating the old string replacement immediately. Rejected because it did
  not establish whether the workaround was still needed.

### 2. Prefer a same-origin Muximux reverse proxy over any RomM bundle patch
Live testing showed that the unpatched RomM image does not crash in a
same-origin iframe, and that the remaining failure path comes from embedding the
public Cloudflare-protected origin inside Muximux. The preferred mitigation is
therefore to proxy RomM through Muximux itself under `/romm/`, using the
internal `http://romm:8080` service name instead of the public hostname or a
container IP.

Why:
- The validated fix targets the actual failing boundary, which is Muximux's
  public-origin embed path, not RomM's startup bundle.
- A same-origin reverse proxy survives RomM frontend rebuilds because it does
  not depend on hashed filenames or minified implementation details.
- Proxying by the Podman service name survives container IP churn.

Alternatives considered:
- Continue patching the active JS bundle with broader regexes. Rejected because
  live validation shows the failure no longer requires a RomM-side patch.
- Inject a new runtime shim into RomM `index.html`. Rejected because the proven
  live mitigation exists one layer higher in Muximux.
- Pin RomM to an older image. Rejected because the current image is not the
  actual root cause.

### 3. Keep RomM startup tolerant and validate the real embed path separately
The host-side workflow should distinguish between:
- RomM startup preparation failures
- validation results that show no RomM-side iframe mitigation is necessary
- Muximux embed-path failures

Why:
- The old failure mode collapsed `patch target changed` into a hard service
  startup failure.
- Separating RomM startup from Muximux embed validation makes future RomM
  upgrades debuggable.

## Risks / Trade-offs

- [The public-origin iframe failure may be partly cache-dependent] -> Validate
  the live Muximux path directly and keep the fix same-origin so it bypasses the
  public Cloudflare layer entirely.
- [RomM may still emit root-relative asset or API paths under `/romm/`] ->
  Proxy both `/romm/` and the leaked `/assets/` and `/api/` requests through
  Muximux, as validated live.
- [The Muximux proxy could drift from the runtime-generated default config] ->
  Install a managed vhost file before container start so the proxy path is
  declarative.

## Migration Plan

1. Temporarily bypass the existing RomM `postStart` patch on `chill-penguin`.
2. Restart RomM on the host and verify whether the unpatched 4.8.0 image still
   fails in iframe mode.
3. Confirm whether the remaining failure path is the public-origin Muximux
   embed rather than RomM itself.
4. Implement the Muximux `/romm/` reverse proxy and tile URL update in
   `modules/self-hosted/muximux.nix`, rebuild the host, and verify startup,
   service health, and iframe behavior.
5. Roll back by switching to the prior NixOS generation if the new Muximux
   proxy path regresses portal availability.

## Open Questions

- Does any other Muximux-managed service rely on root `/assets/` or `/api/`
  paths that would conflict with the RomM proxy locations?
