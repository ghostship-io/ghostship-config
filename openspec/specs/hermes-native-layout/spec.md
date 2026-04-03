# hermes-native-layout Specification

## Purpose
Define the persisted runtime layout and activation contract for the self-hosted
Hermes workstation on `chill-penguin`.

## Requirements
### Requirement: Hermes SHALL use the image's native startup contract
The self-hosted Hermes container definition SHALL use the startup contract
provided by `ghcr.io/ghostship-io/ghostship-hermes:latest` instead of overriding it
with a repo-side startup shim.

#### Scenario: Native image entrypoint is preserved
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL not override the image entrypoint
- **THEN** it SHALL not override the image command with the legacy
  `/hermes-startup.sh` path
- **THEN** it SHALL not depend on a hardcoded Nix store path for
  `ghostship-hermes-runtime`

### Requirement: Hermes SHALL persist state through the workstation data root
The self-hosted Hermes service SHALL persist durable state by mounting the
existing host path `/srv/apps/hermes/home` at `/opt/data` inside the container.

#### Scenario: Durable Hermes data mount is generated
- **WHEN** the Hermes container is configured on `chill-penguin`
- **THEN** `/srv/apps/hermes/home` SHALL be mounted at `/opt/data`
- **AND** the container SHALL not require `/home/hermes/.hermes` to be the
  primary persisted mount target

### Requirement: Hermes SHALL expose a persistent workspace at `/workspace`
The self-hosted Hermes service SHALL expose a direct persistent workspace at
`/workspace` backed by `/srv/apps/hermes/workspace` on `chill-penguin`.

#### Scenario: Hermes workspace mount is generated
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** `/srv/apps/hermes/workspace` SHALL be mounted at `/workspace`
- **AND** `/srv/apps/hermes/workspace` SHALL be managed as a durable host
  directory under `/srv/apps`

### Requirement: Hermes SHALL persist Nix state through a named volume
The self-hosted Hermes service SHALL mount `/nix` through a named Podman volume
so Hermes-managed Nix software and build outputs survive container replacement.

#### Scenario: Hermes Nix volume is configured
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL include a named volume mounted at `/nix`
- **AND** the named volume SHALL not require a host bind mount under
  `/srv/apps/hermes`

### Requirement: Native layout cutover SHALL be verifiable after activation
The Hermes layout migration SHALL provide a clear host-side verification path
after the NixOS switch.

#### Scenario: Post-switch verification
- **WHEN** the updated Hermes service is activated on `chill-penguin`
- **THEN** operators SHALL be able to verify through container inspection that
  Hermes uses `/opt/data` and `/workspace` as the persisted mount targets
- **AND** operators SHALL be able to verify that Hermes mounts a persistent
  `/nix` volume
