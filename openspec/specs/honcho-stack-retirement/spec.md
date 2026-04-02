# honcho-stack-retirement Specification

## Purpose
TBD - created by archiving change remove-honcho-stack. Update Purpose after archive.

## Requirements
### Requirement: Ghostship SHALL not manage the Honcho runtime after retirement
The self-hosted configuration SHALL stop managing the Honcho app, database, and Redis containers once the Honcho stack is retired.

#### Scenario: Host configuration omits Honcho services
- **WHEN** the self-hosted NixOS modules are evaluated after the retirement change
- **THEN** the Honcho service module is not imported
- **AND** the host configuration does not declare managed Honcho app, database, or Redis containers

### Requirement: Hermes SHALL not depend on Honcho after retirement
Hermes SHALL not export Honcho integration settings or preserve Honcho compatibility-state management after the Honcho stack is retired.

#### Scenario: Hermes no longer advertises Honcho integration
- **WHEN** the Hermes container configuration is generated after the retirement change
- **THEN** `HONCHO_API_KEY` and `HONCHO_BASE_URL` are not exported to Hermes
- **AND** Hermes no longer manages retained Honcho compatibility state under its home directory

### Requirement: Honcho retirement SHALL remove Honcho-only secrets and host state
The retirement workflow SHALL remove the Honcho-only `litellm-secrets` reference from the repo and SHALL clean retired Honcho state from `chill-penguin`.

#### Scenario: Repo secrets no longer include Honcho-only configuration
- **WHEN** the retirement change is implemented
- **THEN** the self-hosted secrets configuration no longer declares `litellm-secrets`
- **AND** the corresponding encrypted secret material is removed from the repo

#### Scenario: Host cleanup removes retired Honcho state
- **WHEN** the retired stack is deployed and cleaned on `chill-penguin`
- **THEN** the persisted Honcho state under `/srv/apps/honcho`, `/srv/apps/honcho-db`, and `/srv/apps/honcho-redis` is removed
- **AND** Hermes’ retained Honcho compatibility state is removed from `/srv/apps/hermes/home/shared/honcho`
