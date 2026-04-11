## ADDED Requirements

### Requirement: Hermes SHALL use one authoritative managed runtime surface
The self-hosted Hermes deployment on `chill-penguin` SHALL treat `/home/hermes/.hermes` as the one authoritative managed runtime surface and SHALL not depend on a repo-owned named-profile fleet for normal operation.

#### Scenario: Single-agent runtime is the only managed surface
- **WHEN** the Hermes container definition and host wiring are evaluated after this change
- **THEN** `/home/hermes/.hermes` SHALL be the primary managed runtime path
- **AND** the supported contract SHALL not require `assistant`, `operations`, or `supervisor` profile homes under `~/.hermes/profiles/`
- **AND** repo-managed workflows SHALL not depend on profile-local `.env`, skill, or `SOUL.md` paths

### Requirement: Single-agent cutover SHALL reset persisted Hermes state before deployment
The deployment workflow for the single-agent Hermes cutover SHALL remove the old persisted Hermes state before the updated image is started on `chill-penguin`.

#### Scenario: Pre-deploy reset removes stale persisted state
- **WHEN** operators deploy the single-agent Hermes contract to `chill-penguin`
- **THEN** they SHALL stop Hermes and remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before starting the updated service
- **AND** the updated service SHALL recreate clean persisted state that matches the new single-agent layout

### Requirement: Hermes SHALL not configure a remote browser default through host wiring
The self-hosted Hermes host wiring SHALL leave upstream local-browser behavior as the default and SHALL not emit a repo-managed remote browser CDP endpoint.

#### Scenario: Browser CDP defaults are omitted from generated host wiring
- **WHEN** the Hermes container environment is generated after this change
- **THEN** it SHALL not include `BROWSER_CDP_URL`
- **AND** it SHALL not include `BROWSER_ASSISTANT_CDP_URL`, `BROWSER_OPERATIONS_CDP_URL`, or `BROWSER_SUPERVISOR_CDP_URL`
