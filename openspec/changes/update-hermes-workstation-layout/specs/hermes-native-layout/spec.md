## ADDED Requirements

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
- **AND** `/srv/apps/hermes/workspace` SHALL remain a durable host directory
  under `/srv/apps`

### Requirement: Hermes SHALL persist Nix state through a named volume
The self-hosted Hermes service SHALL mount `/nix` through a named Podman volume
so Hermes-managed Nix software and build outputs survive container replacement.

#### Scenario: Hermes Nix volume is configured
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL include a named volume mounted at `/nix`
- **AND** the named volume SHALL not require a host bind mount under
  `/srv/apps/hermes`

## MODIFIED Requirements

### Requirement: Native layout cutover SHALL be verifiable after activation
The Hermes layout migration SHALL provide a clear host-side verification path
after the NixOS switch.

#### Scenario: Post-switch verification
- **WHEN** the updated Hermes service is activated on `chill-penguin`
- **THEN** operators SHALL be able to verify through container inspection that
  Hermes uses `/opt/data` and `/workspace` as the persisted mount targets
- **AND** operators SHALL be able to verify that Hermes mounts a persistent
  `/nix` volume

## REMOVED Requirements

### Requirement: Hermes SHALL persist state through the native Hermes home layout
**Reason**: The workstation-style Hermes image no longer uses
`/home/hermes/.hermes` as the primary persisted mount target.
**Migration**: Mount the existing host path `/srv/apps/hermes/home` at
`/opt/data` instead.

### Requirement: Hermes SHALL expose a persistent workspace outside HERMES_HOME
**Reason**: `/workspace` is now the canonical persistent workspace mount target.
**Migration**: Mount `/srv/apps/hermes/workspace` at `/workspace` and treat any
`/home/hermes/workspace` path as image-owned compatibility only.

### Requirement: Legacy Honcho config SHALL be migrated into the native Hermes layout
**Reason**: The current repo-managed Hermes contract no longer relies on a
host-side Honcho migration step, and the workstation layout change is centered
on `/opt/data`, `/workspace`, and `/nix`.
**Migration**: Do not add new host-side Honcho migration logic as part of this
layout update.
