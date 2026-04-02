## Why

The stale RomM bundle rewrite was removed and `podman-romm.service` now starts
cleanly on `chill-penguin`. Repointing Muximux at a same-origin `/romm/` proxy
also removed the public Cloudflare Access boundary that used to block the
iframe. That was necessary, but it was not sufficient: Chrome still hits a
framed RomM frontend failure during the real Muximux login render.

The old live notes already showed that removing the router `beforeResolve`
wait stopped the hard iframe wedge but still exposed a `null.refs` runtime
error. Repeating that rewrite manually on the current image again stops the
hard crash, but it leaves the login view blank and depends on editing the
served RomM bundle directly. The repo now needs a more durable mitigation that
keeps RomM unmodified and instead injects an iframe-only runtime shim from the
Muximux reverse proxy before RomM boots.

## What Changes

- Reproduce the current same-origin Muximux failure on `chill-penguin` and
  capture the direct `/romm/` versus `/#RomM` behavior so the remaining bug is
  clearly separated from the already-fixed Cloudflare/public-origin issue.
- Replace the ad hoc live RomM bundle rewrite with a managed iframe-only shim
  injected by the Muximux `/romm/` reverse proxy before RomM's main module
  executes.
- Keep the shim targeted at stable browser/runtime APIs in framed loads instead
  of hashed filenames or one exact minified bundle string.
- Remove any temporary live RomM file edits once the proxy-managed shim is
  active and verified.
- Update the Muximux host module, change artifacts, and supporting docs only
  after the shim is proven against the real embedding path.

## Capabilities

### New Capabilities
- `romm-iframe-resilience`: Validate the live Muximux-to-RomM iframe behavior
  on the server host and keep any required iframe mitigation durable across
  RomM image updates without editing the served RomM bundle.

### Modified Capabilities

## Impact

- Affects `chill-penguin` and the Muximux host definition under
  `modules/self-hosted/muximux.nix`; `modules/self-hosted/romm.nix` stays free
  of frontend bundle patch logic.
- Requires live host-side validation against both direct `/romm/` and the real
  Muximux `/#RomM` iframe path before the repo change is considered valid.
- May require temporary live container inspection or manual file edits inside
  the running Muximux config volume while validating the shim behavior before
  the NixOS module is updated.
