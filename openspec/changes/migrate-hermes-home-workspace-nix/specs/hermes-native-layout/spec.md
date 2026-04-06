## ADDED Requirements

### Requirement: Hermes SHALL persist Nix state through a host-mounted seedable path
The self-hosted Hermes service SHALL mount `/nix` from a persistent host path
under `/srv/apps/hermes` so Hermes-managed Nix software and build outputs
survive container replacement without depending on Podman volume lifecycle.

#### Scenario: Host-mounted `/nix` path is configured
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL mount a host path under `/srv/apps/hermes` at `/nix`
- **AND** it SHALL not rely on a named Podman volume for the `/nix` mount

### Requirement: Hermes SHALL seed the persistent `/nix` path before first mounted start
The Hermes migration SHALL initialize the persistent host path used for `/nix`
from the image before the container starts with `/nix` mounted.

#### Scenario: Empty `/nix` host path is prepared before cutover
- **WHEN** the persistent Hermes `/nix` host path is missing or empty during
  the first whole-home cutover
- **THEN** the migration path SHALL seed that host path from the current image
- **AND** the Hermes container SHALL not start with an empty `/nix` bind mount
  that hides the image's `/nix` content

## MODIFIED Requirements

### Requirement: Hermes SHALL persist state through the workstation data root
The self-hosted Hermes service SHALL persist durable state by mounting the
existing host path `/srv/apps/hermes/home` at `/home/hermes` inside the
container.

#### Scenario: Durable Hermes home mount is generated
- **WHEN** the Hermes container is configured on `chill-penguin`
- **THEN** `/srv/apps/hermes/home` SHALL be mounted at `/home/hermes`
- **AND** the container SHALL treat `/home/hermes/.hermes` as managed Hermes
  state within that persisted home tree
- **AND** the container SHALL not require `/opt/data` to be the primary
  persisted mount target

### Requirement: Native layout cutover SHALL be verifiable after activation
The Hermes layout migration SHALL provide a clear host-side verification path
after the NixOS switch.

#### Scenario: Post-switch verification
- **WHEN** the updated Hermes service is activated on `chill-penguin`
- **THEN** operators SHALL be able to verify through container inspection that
  Hermes uses `/home/hermes` and `/workspace` as the persisted mount targets
- **AND** operators SHALL be able to verify that Hermes mounts a persistent
  host-backed `/nix` path
- **AND** operators SHALL be able to verify that `/home/hermes/.hermes` exists
  within the persisted home tree

## REMOVED Requirements

### Requirement: Hermes SHALL persist Nix state through a named volume
**Reason**: The current Hermes runtime needs a deterministic, host-managed
`/nix` path that can be seeded from the image before first mounted start, and a
named Podman volume hides too much lifecycle and copy-up behavior for that
critical path.

**Migration**: Replace the named `/nix` volume with a host bind mount under
`/srv/apps/hermes`, seed that host path from the image, and verify the mounted
`/nix` tree after the host switch.
