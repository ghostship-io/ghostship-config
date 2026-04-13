## REMOVED Requirements

### Requirement: Hermes SHALL persist state through the workstation data root
**Reason**: The upstream single-agent contract persists the interactive home directly at `/home/hermes` instead of the older `/opt/data` layout.
**Migration**: Mount `/srv/apps/hermes/home` at `/home/hermes` and verify the root-managed runtime under `/home/hermes/.hermes` after cutover.

### Requirement: Hermes SHALL persist Nix state through a named volume
**Reason**: This repo now persists Hermes `/nix` state through the host-managed bind mount `/srv/apps/hermes/nix` rather than a named Podman volume.
**Migration**: Remove the old persisted `/srv/apps/hermes/nix` tree during the destructive reset, then let the updated service recreate it as the `/nix` bind mount source.

## ADDED Requirements

### Requirement: Hermes SHALL persist state through the workstation home mount
The self-hosted Hermes service SHALL persist durable state by mounting the existing host path `/srv/apps/hermes/home` at `/home/hermes` inside the container.

#### Scenario: Durable Hermes home mount is generated
- **WHEN** the Hermes container is configured on `chill-penguin` after this change
- **THEN** `/srv/apps/hermes/home` SHALL be mounted at `/home/hermes`
- **AND** `/home/hermes/.hermes` SHALL be the primary managed runtime path inside that persisted home mount

### Requirement: Hermes SHALL persist Nix state through a host bind mount
The self-hosted Hermes service SHALL mount `/nix` from the host-managed path `/srv/apps/hermes/nix` so image-owned Nix state can be reseeded after the destructive cutover and then persist across replacement.

#### Scenario: Durable Hermes Nix bind mount is generated
- **WHEN** the Hermes container definition is evaluated for `chill-penguin` after this change
- **THEN** `/srv/apps/hermes/nix` SHALL be mounted at `/nix`
- **AND** `/srv/apps/hermes/nix` SHALL be treated as destructive-reset state during the single-agent cutover

## MODIFIED Requirements

### Requirement: Native layout cutover SHALL be verifiable after activation
The Hermes layout migration SHALL provide a clear host-side verification path after the NixOS switch and destructive reset.

#### Scenario: Post-switch verification
- **WHEN** the updated Hermes service is activated on `chill-penguin`
- **THEN** operators SHALL be able to verify through container inspection that Hermes uses `/home/hermes`, `/workspace`, and `/nix` as the persisted mount targets
- **AND** operators SHALL be able to verify that the old `~/.hermes/profiles/` tree is absent from the reset runtime state
