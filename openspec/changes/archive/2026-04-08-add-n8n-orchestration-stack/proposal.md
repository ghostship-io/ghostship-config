## Why

Ghostship does not currently have a first-class orchestration engine for larger cross-service workflows. Adding `n8n` now creates a durable workflow surface for Hermes and operators while keeping the initial rollout simple: a single SQLite-backed instance behind the existing Cloudflare access pattern.

## What Changes

- Add a new self-hosted `n8n` service to the `chill-penguin` stack with a persisted SQLite data directory and repo-managed runtime configuration.
- Expose `n8n` on the internal Ghostship network for Hermes API access while keeping browser access on the public hostname behind Cloudflare.
- Add a Homepage `Services` tile for `n8n`.
- Add an `n8n` entry to the declarative Muximux configuration intended to appear immediately after `Bazarr` in the dropdown.
- Document that the live Muximux ordering on `chill-penguin` still needs a one-time manual reorder after deployment so the new tile lands directly under `Bazarr`.
- Seed the required `n8n` secrets and Hermes-facing integration environment so Hermes can call the `n8n` API without routing through the public hostname.

## Capabilities

### New Capabilities
- `n8n-service`: Adds a single-instance, SQLite-backed `n8n` runtime with persisted state, Cloudflare-gated browser access, and Hermes API integration.

### Modified Capabilities
- `muximux-service-placement`: Extend the generated Muximux layout so `n8n` belongs in the dropdown immediately after `Bazarr`, with rollout notes covering the required manual host-side reorder on `chill-penguin`.

## Impact

- Affects server-host NixOS modules under `modules/self-hosted/`, especially a new `n8n` module plus `default.nix`, `homepage.nix`, `muximux.nix`, and `secrets.nix`.
- Requires new encrypted secrets for the `n8n` runtime and Hermes integration.
- Requires host activation on `chill-penguin` and a manual post-deploy Muximux reorder on the live host.
- Assumes the public `n8n.ghostship.io` route continues to be managed through the existing Cloudflare/tunnel workflow rather than a repo-managed ingress definition.
