## MODIFIED Requirements

### Requirement: Hermes SHALL persist Nix state through a host bind mount
The self-hosted Hermes service SHALL mount `/nix` from the host-managed path
`/srv/apps/hermes/nix` so image-owned Nix defaults can be seeded on a fresh
boot and reconciled on later boots while user-managed Nix state remains
persisted.

#### Scenario: Durable Hermes Nix bind mount is generated
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** `/srv/apps/hermes/nix` SHALL be mounted at `/nix`
- **AND** an empty recreated `/srv/apps/hermes/nix` SHALL be safe because the
  image seeds `/nix` on first boot
- **AND** a reused non-empty `/srv/apps/hermes/nix` SHALL be supported through
  boot-time reconciliation of the image-managed default profile at
  `/nix/var/nix/profiles/per-user/hermes/ghostship-defaults`
- **AND** that reconciliation SHALL not require deleting unrelated
  user-managed Nix content

### Requirement: Native layout cutover SHALL be verifiable after activation
The Hermes layout migration SHALL provide a clear host-side verification path
after the NixOS switch and full reset.

#### Scenario: Post-switch verification
- **WHEN** the updated Hermes service is activated on `chill-penguin` after a
  full reset
- **THEN** operators SHALL be able to verify through container inspection that
  Hermes uses `/home/hermes`, `/workspace`, and `/nix` as the persisted mount
  targets
- **AND** operators SHALL be able to verify that the fresh `/nix` path has the
  image-managed default profile available
- **AND** operators SHALL be able to verify that the old `~/.hermes/profiles/`
  tree is absent from the reset runtime state
