## Why

The `chill-penguin` Hermes container currently exposes only part of the
runtime environment that the shipped `ghostship-hermes` image and bundled
`ghostship-*` utilities expect. As a result, several packaged utilities are not
usable from Hermes even though the backing services, credentials, and profile
topology already exist in the stack.

## What Changes

- Expand the Hermes container runtime env contract so bundled `ghostship-*`
  utilities receive the service URLs and credentials they need from
  explicit local env wiring that selectively reads the required values from
  existing service-local secret bundles and generated runtime env files.
- Add a managed Hermes utility/runtime env capability that defines which
  service URLs, service credentials, and profile-facing browser defaults SHALL
  be available to the three managed Hermes profiles.
- Wire per-profile CloakBrowser CDP defaults into the managed Hermes profile
  `.env` files so `assistant`, `operations`, and `supervisor` each get their
  own default `BROWSER_CDP_URL`.
- Keep the router scope minimal by wiring only the provider/runtime env already
  needed for the current fallback and router flow, not the broader
  `GHOSTSHIP_ROUTER_*` tuning surface.
- Document the managed Hermes runtime env contract and any required host
  activation or verification steps for the server-host rollout.

## Capabilities

### New Capabilities
- `hermes-utility-runtime-env`: Define the runtime env contract that makes the
  managed Hermes profiles and bundled `ghostship-*` utilities usable against
  the existing Ghostship self-hosted stack, including per-profile CloakBrowser
  CDP defaults.

### Modified Capabilities
- `changedetection-service`: Clarify that the managed CloakBrowser profile set
  remains the source of truth for profile-backed CDP endpoints, while Hermes
  can reuse the same managed profile inventory for profile-specific browser
  defaults without forcing those Hermes-facing profiles to stay launched.

## Impact

- Affected systems: server hosts, especially `chill-penguin`; self-hosted
  Hermes runtime; CloakBrowser profile integration; selected secret extraction and projection; bundled `ghostship-*`
  utility ergonomics.
- Affected code: [hermes.nix](/home/nixos/nixos-config/modules/self-hosted/hermes.nix),
  related self-hosted service modules and secret references, and repo
  documentation in `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Deployment implications: requires host activation on `chill-penguin`; uses a host-managed profile env reconciliation step after the image bootstrap so
  managed profile `.env` files receive per-profile `BROWSER_CDP_URL` values
  without requiring a separate upstream image rollout first.
