## Why

The stale RomM bundle rewrite was removed and `podman-romm.service` now starts
cleanly on `chill-penguin`. Live validation showed that RomM 4.8.0 also loads
inside a same-origin iframe without the old bundle patch. The remaining failure
path is specific to Muximux embedding the public
`https://romm.ghostship.io` origin, which is fronted by Cloudflare Access and
is not a stable iframe target. The repo needs to preserve the verified manual
host fix: Muximux should embed RomM through a local same-origin reverse proxy
instead of the public hostname.

## What Changes

- Verify on `chill-penguin` whether the current RomM image still reproduces the
  iframe crash through the real Muximux iframe path now that the startup patch
  is gone.
- Document the live failure mode and distinguish Muximux-specific public-origin
  iframe failures from RomM service startup issues.
- Test and verify the host-side mitigation directly on `chill-penguin` before
  changing the NixOS module, so the repo only carries a fix that is already
  proven against the real embedding path.
- Replace the broken public-origin Muximux embed with a durable same-origin
  reverse proxy path that uses the internal RomM service name instead of a
  container IP.
- Update the Muximux host module and any affected docs only after the manual
  fix path is understood and verified.

## Capabilities

### New Capabilities
- `romm-iframe-resilience`: Validate unpatched RomM iframe behavior on the
  server host and keep any required iframe mitigation durable across RomM image
  updates.

### Modified Capabilities

## Impact

- Affects `chill-penguin` and the self-hosted RomM service definition under
  `modules/self-hosted/romm.nix` plus the Muximux host definition under
  `modules/self-hosted/muximux.nix`.
- Requires live host-side validation against Muximux before any further repo
  config changes are considered valid.
- May require temporary live container inspection or manual file edits inside
  the running Muximux config volume while validating the real iframe failure
  mode.
