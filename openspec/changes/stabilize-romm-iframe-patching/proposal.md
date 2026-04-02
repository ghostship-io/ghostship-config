## Why

The live `rommapp/romm:latest` upgrade to RomM 4.8.0 changed the frontend
bundle shape enough that the current post-start iframe patch no longer matches,
which leaves `podman-romm.service` failed during startup. The repo needs a
repeatable way to validate whether the unpatched image still crashes in iframe
contexts and, if it does, a mitigation that survives routine upstream bundle
renames and minifier changes.

## What Changes

- Verify on `chill-penguin` whether the current RomM image still reproduces the
  iframe crash when started without the repo’s post-start bundle rewrite.
- Document the live failure mode and distinguish startup-hook failures from the
  underlying iframe regression.
- Replace the brittle single-string frontend patch with a more durable
  mitigation strategy that can tolerate upstream asset renames and minor bundle
  rewrites.
- Update the RomM host module and any affected docs for the new verification
  and mitigation flow.

## Capabilities

### New Capabilities
- `romm-iframe-resilience`: Validate unpatched RomM iframe behavior on the
  server host and keep any required iframe mitigation durable across RomM image
  updates.

### Modified Capabilities

## Impact

- Affects `chill-penguin` and the self-hosted RomM service definition under
  `modules/self-hosted/romm.nix`.
- Requires server-host activation to test and ship the final mitigation.
- May require temporary live container inspection or cleanup while validating
  unpatched and patched startup behavior.
