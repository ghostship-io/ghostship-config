## Why

`chill-penguin` still runs Hermes through legacy repo-side image overrides even
though `ghcr.io/ghostship-io/ghostship-hermes:latest` now ships its own supported
entrypoint and native state layout. That drift keeps the host pinned to old
startup behavior, hardcodes store paths into the container launch path, and
blocks clean alignment with the image that is actually being deployed.

## What Changes

- Remove the repo-side Hermes startup shim, entrypoint override, command
  override, and hardcoded runtime store path from the self-hosted module.
- Stop bind-mounting legacy image compatibility paths that the Hermes image now
  manages itself, including the writable `/nix` volume and the separate
  `/home/hermes/.honcho` bind mount.
- Preserve Hermes durable state by keeping the native `HERMES_HOME`
  bind mount at `/home/hermes/.hermes`.
- Add a one-time migration path that moves the current Honcho config from the
  legacy host path into the native Hermes layout expected by the image.
- Update documentation and agent memory for the native Hermes image contract and
  any required host activation steps.

## Capabilities

### New Capabilities
- `hermes-native-layout`: Defines how the self-hosted Hermes service uses the
  image's native entrypoint, native state layout, and native Honcho
  compatibility layout on server hosts.

### Modified Capabilities
- None.

## Impact

- Affected systems: server hosts running the self-hosted Hermes container,
  especially `chill-penguin`; no develop-host or Home Manager behavior changes.
- Affected code: `modules/self-hosted/hermes.nix` plus supporting docs in
  `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Host activation implications: the change requires a host rebuild/switch and a
  one-time migration of the legacy Honcho config from
  `/srv/apps/hermes/home/.honcho/config.json` into the Hermes image's native
  layout. Legacy compatibility directories may need cleanup after the cutover.
