## MODIFIED Requirements

### Requirement: Single-agent cutover SHALL reset persisted Hermes state before deployment
The deployment workflow for the single-agent Hermes contract on `chill-penguin` SHALL remove all persisted workstation state before the refreshed image is started.

#### Scenario: Pre-deploy reset removes stale persisted state
- **WHEN** operators deploy the refreshed Hermes runtime contract to
  `chill-penguin`
- **THEN** they SHALL stop Hermes and remove `/srv/apps/hermes/home`,
  `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before starting the
  updated service
- **AND** the reset SHALL discard persisted auth, memories, logs, XDG/userland
  state, custom skills, workspace contents, and user-installed Nix state from
  the previous runtime
- **AND** the updated service SHALL recreate clean persisted state that matches
  the current single-agent layout
- **AND** the rollout SHALL start the latest published
  `ghcr.io/ghostship-io/ghostship-hermes:latest` image rather than a stale cached
  image

## ADDED Requirements

### Requirement: Fresh single-agent runtime SHALL rebuild only from image defaults and supported host inputs
The fresh Hermes runtime created after a full reset SHALL rebuild its initial
state from the image-owned workstation defaults plus supported host-provided
runtime env and mounts.

#### Scenario: Fresh runtime does not inherit stale managed state
- **WHEN** Hermes boots for the first time after the full reset
- **THEN** the fresh runtime SHALL not inherit stale managed runtime state from
  the deleted home, workspace, or `/nix` paths
- **AND** the fresh runtime SHALL rely on current image-owned defaults for its
  initial workstation state
- **AND** operators SHALL need to perform any required fresh setup such as
  Codex auth inside the new persisted home
