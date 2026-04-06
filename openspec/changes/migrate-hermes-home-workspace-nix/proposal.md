## Why

The self-hosted Hermes integration in this repo still documents and mounts the
April 3, 2026 workstation contract built around `/opt/data`, but the current
`ghcr.io/ghostship-io/ghostship-hermes:latest` image has moved to a whole-home runtime
contract with first-class profile gateways, in-image routing services, and
runtime skill seeding. We need to migrate now so `chill-penguin` stays aligned
with the supported upstream image contract instead of relying on stale mounts,
stale docs, and incomplete environment wiring.

## What Changes

- **BREAKING** Update the Hermes persistence contract on the server host from
  `/srv/apps/hermes/home -> /opt/data` to `/srv/apps/hermes/home -> /home/hermes`.
- **BREAKING** Replace the Hermes `/nix` named Podman volume with a persisted
  host path under `/srv/apps/hermes` and seed that path from the image before
  the first mounted start so the image store is not hidden by an empty mount.
- Keep `/srv/apps/hermes/workspace -> /workspace` as the persistent work mount.
- Expand the Hermes runtime contract so the three managed profile gateways
  (`assistant`, `operations`, and `supervisor`) are first-class runtime
  services, not just incidental image internals.
- Add Hermes runtime skill-seeding scaffolding from `/home/hermes/seeds/...`
  so shared and per-profile skills can be staged into Hermes-owned state
  without overwriting existing user-managed content.
- Expand Hermes environment wiring so the profile gateways, bootstrap path, and
  router receive the required Ghostship service URLs, secrets, model-provider
  credentials, Discord settings, and router configuration.
- Update the repo documentation and OpenSpec artifacts to describe the new
  contract and the required host activation and migration steps on
  `chill-penguin`.

## Capabilities

### New Capabilities
- `hermes-profile-gateway-runtime`: Define Hermes profile-gateway-first runtime
  behavior, including skill seeding from `/home/hermes/seeds/...` and the
  required environment propagation for gateways, bootstrap, and router
  services.

### Modified Capabilities
- `hermes-native-layout`: Replace the stale `/opt/data` and named-volume `/nix`
  requirements with persisted `/home/hermes`, `/workspace`, and host-mounted
  seeded `/nix` requirements for the current image contract.

## Impact

- Affected code: `modules/self-hosted/hermes.nix`, `modules/self-hosted/secrets.nix`,
  and any supporting NixOS wiring needed for Hermes runtime preparation.
- Affected docs and planning artifacts: `README.md`, `CHANGELOG.md`,
  `AGENTS.md`, and `openspec/specs/hermes-native-layout/spec.md`, plus a new
  Hermes profile gateway runtime spec.
- Affected system: `chill-penguin` server host. This change requires a host
  activation and a one-time Hermes `/nix` seed/cutover path before the new
  runtime mounts are treated as valid.
