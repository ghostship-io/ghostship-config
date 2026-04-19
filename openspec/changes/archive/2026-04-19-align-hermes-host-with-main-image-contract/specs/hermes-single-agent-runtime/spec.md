## MODIFIED Requirements

### Requirement: Hermes SHALL use one authoritative managed runtime surface
The self-hosted Hermes deployment on `chill-penguin` SHALL treat the current `ghostship-hermes` `main` workstation image contract as the source of truth for runtime ownership and SHALL keep `/home/hermes/.hermes` as the one authoritative managed runtime surface.

#### Scenario: Single-agent runtime is the only managed surface
- **WHEN** the Hermes container definition and host wiring are evaluated for the current `ghostship-hermes` `main` image
- **THEN** `/home/hermes/.hermes` SHALL be the primary managed runtime path
- **AND** the supported contract SHALL not require `assistant`, `operations`, or `supervisor` profile homes under `~/.hermes/profiles/`
- **AND** repo-managed workflows SHALL not depend on profile-local `.env`, skill, or `SOUL.md` paths
- **AND** repo-managed host wiring SHALL not depend on staging runtime defaults under `/home/hermes/seeds/`

#### Scenario: Image-owned workstation supervision remains authoritative
- **WHEN** the Hermes container starts with the current `ghostship-hermes` `main` image
- **THEN** the long-running Hermes gateway, dashboard, router, published web listener, and terminal sidecar SHALL be owned by the image-side supervision path
- **AND** repo-managed host wiring SHALL not exec `systemctl` inside the container to start Hermes runtime services

### Requirement: Single-agent cutover SHALL reset persisted Hermes state before deployment
The deployment workflow for the current `ghostship-hermes` `main` image cutover SHALL remove the old persisted Hermes state before the updated image is started on `chill-penguin`.

#### Scenario: Pre-deploy reset removes stale persisted state
- **WHEN** operators deploy the current `ghostship-hermes` `main` image contract to `chill-penguin`
- **THEN** they SHALL stop the Hermes container and remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before starting the updated image
- **AND** the updated image SHALL start only after those persisted directories are reset
- **AND** the updated service SHALL recreate clean persisted state that matches the current workstation layout

## ADDED Requirements

### Requirement: Hermes SHALL rely on image-owned first-boot Nix seeding
The self-hosted Hermes host wiring SHALL rely on the current `ghostship-hermes` image to seed an empty persisted `/nix` mount during first boot instead of pre-populating `/srv/apps/hermes/nix` from a separate host-side seed container.

#### Scenario: Empty persisted Nix mount is accepted during the destructive cutover
- **WHEN** `/srv/apps/hermes/nix` is recreated empty during the destructive rollout for the current image
- **THEN** repo-managed host wiring SHALL mount that path at `/nix` without performing a separate host-side seed copy first
- **AND** the image's first-boot init path SHALL be allowed to seed `/nix` itself
