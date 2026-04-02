# hermes-native-layout Specification

## Purpose
TBD - created by archiving change native-hermes-layout. Update Purpose after archive.

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

### Requirement: Hermes SHALL persist state through the native Hermes home layout
The self-hosted Hermes service SHALL persist durable state through the image's
native `HERMES_HOME` layout at `/home/hermes/.hermes`.

#### Scenario: Durable Hermes state mount is preserved
- **WHEN** the Hermes container is configured on `chill-penguin`
- **THEN** `/srv/apps/hermes/home` SHALL remain mounted at
  `/home/hermes/.hermes`
- **THEN** the legacy writable `/nix` volume SHALL not be required for normal
  Hermes startup
- **THEN** the separate `/home/hermes/.honcho` bind mount SHALL not be used

### Requirement: Hermes SHALL expose a persistent workspace outside HERMES_HOME
The self-hosted Hermes service SHALL expose a direct persistent workspace at
`/home/hermes/workspace` backed by `/srv/apps/hermes/workspace` on
`chill-penguin`.

#### Scenario: Hermes workspace bind mount is generated
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** `/srv/apps/hermes/workspace` SHALL be mounted at
  `/home/hermes/workspace`
- **AND** `/srv/apps/hermes/workspace` SHALL be managed as a durable host
  directory under `/srv/apps`
- **AND** the existing Hermes home mount at `/home/hermes/.hermes` SHALL remain
  in place

### Requirement: Legacy Honcho config SHALL be migrated into the native Hermes layout
The self-hosted Hermes migration SHALL preserve the existing Honcho config by
moving it into the image's native shared Honcho location.

#### Scenario: Existing Honcho config is present on the host
- **WHEN** `/srv/apps/hermes/home/.honcho/config.json` exists before the Hermes
  cutover
- **THEN** the migration SHALL create
  `/srv/apps/hermes/home/shared/honcho/config.json`
- **THEN** the migrated config SHALL preserve the existing Honcho host settings
- **THEN** Hermes startup SHALL not require the legacy host path to remain bind
  mounted separately

### Requirement: Native layout cutover SHALL be verifiable after activation
The Hermes native-layout migration SHALL provide a clear host-side verification
path after the NixOS switch.

#### Scenario: Post-switch verification
- **WHEN** the updated Hermes service is activated on `chill-penguin`
- **THEN** operators SHALL be able to verify through container inspection that
  Hermes uses the image's native startup contract
- **THEN** operators SHALL be able to verify that the Honcho config is
  available through the native Hermes layout
