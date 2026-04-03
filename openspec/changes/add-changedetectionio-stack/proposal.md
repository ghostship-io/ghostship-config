## Why

`changedetection.io` is not part of the current Ghostship stack, so there is no
repo-managed way to run page-change monitoring alongside the existing internal
services. The requested rollout also depends on a dedicated CloakBrowser
profile and dashboard placement, so the durable fix belongs in the server-host
Nix modules and specs now rather than as ad hoc host edits later.

## What Changes

- Add a repo-managed `changedetection.io` service to the self-hosted Podman
  stack on `chill-penguin`, with durable application state and internal
  networking.
- Configure the service to use a dedicated default CloakBrowser profile through
  the manager CDP endpoint so browser-backed checks can target a stable
  Ghostship-owned profile.
- Add `Changedetection` to Homepage's `Services` section and add a Muximux tile
  immediately after `RSS-Bridge`.
- Document the new stack component and any deployment or host-activation
  implications in the repo docs.

## Capabilities

### New Capabilities
- `changedetectionio-service`: Define how Ghostship manages changedetection.io,
  including the service container, CloakBrowser default-profile integration,
  and dashboard visibility.

### Modified Capabilities
- `muximux-service-placement`: Update the generated portal layout so
  `Changedetection` appears immediately after `RSS-Bridge`.

## Impact

- Affects server-host NixOS modules under `modules/self-hosted/`, especially
  the self-hosted inventory, CloakBrowser bootstrap, Homepage config, and
  Muximux config.
- Requires host activation on `chill-penguin` to create the new container,
  persistent app state, and dashboard entries.
- May require manual external ingress or Cloudflare tunnel mapping for a new
  public hostname if that routing is still managed outside this repo.
- Requires README, CHANGELOG, and AGENTS updates because the supported service
  inventory and dashboard behavior change.
