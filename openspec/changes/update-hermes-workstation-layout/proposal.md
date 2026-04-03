## Why

Hermes on `chill-penguin` is moving to a new workstation-style image contract
that no longer uses `/home/hermes/.hermes` and `/home/hermes/workspace` as the
primary persisted mount targets. The repo needs to align its NixOS container
definition and documentation with the new image layout before the next Hermes
image rollout.

## What Changes

- **BREAKING** Update the Hermes durable data mount target from
  `/home/hermes/.hermes` to `/opt/data` while keeping the existing host path
  `/srv/apps/hermes/home`.
- **BREAKING** Update the Hermes workspace mount target from
  `/home/hermes/workspace` to `/workspace` while keeping the existing host path
  `/srv/apps/hermes/workspace`.
- Reintroduce a persistent `/nix` mount for Hermes as a named Podman volume so
  user-installed Nix software and build outputs can survive container
  replacement.
- Replace the current Hermes layout contract in OpenSpec, README, CHANGELOG,
  and AGENTS so the repo documents `/opt/data`, `/workspace`, and persisted
  `/nix` instead of the retired native-home layout.
- Define host activation and verification expectations for the `chill-penguin`
  server host, including any one-time Hermes volume inspection or cleanup
  needed after cutover.

## Capabilities

### New Capabilities

### Modified Capabilities
- `hermes-native-layout`: Hermes layout requirements now target `/opt/data`
  and `/workspace`, and Hermes persists `/nix` as part of the new workstation
  runtime contract.

## Impact

- Affected code: `modules/self-hosted/hermes.nix`
- Affected docs: `openspec/specs/hermes-native-layout/spec.md`, `README.md`,
  `CHANGELOG.md`, and `AGENTS.md`
- Affected systems: `chill-penguin` server host and its Podman-managed Hermes
  container
- Activation implications: host rebuild plus Hermes container recreation on the
  target host
- Cleanup implications: old container-target assumptions under
  `/home/hermes/.hermes` and `/home/hermes/workspace` must be retired from repo
  docs and verification steps; existing host data remains in place under
  `/srv/apps/hermes/*`
