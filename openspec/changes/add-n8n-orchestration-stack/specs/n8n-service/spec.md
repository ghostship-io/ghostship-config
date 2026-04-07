## ADDED Requirements

### Requirement: n8n SHALL run as a persisted self-hosted orchestration service
The `chill-penguin` stack SHALL provide a single self-hosted `n8n` service with persistent host-backed state so workflows, credentials, and SQLite data survive container replacement and host reactivation.

#### Scenario: Host configuration defines persisted n8n state
- **WHEN** the `chill-penguin` host configuration is generated from the repo-managed modules
- **THEN** it includes an `n8n` container definition on `ghostship_net`
- **AND** it mounts a persistent host path for the `n8n` application home and SQLite state
- **AND** it does not require separate Postgres, Redis, or worker services for this change

### Requirement: n8n SHALL separate browser access from Hermes API access
The system SHALL expose `n8n` for browser users on the public Ghostship hostname while also providing an internal network path for Hermes to call the `n8n` API directly with a dedicated API key.

#### Scenario: Public and internal access paths are both configured
- **WHEN** the `n8n` runtime configuration is generated
- **THEN** browser access is anchored to `https://n8n.ghostship.io`
- **AND** Hermes-facing configuration uses an internal service URL on `ghostship_net`
- **AND** the Hermes integration relies on an `n8n` API key instead of the public browser session flow

### Requirement: n8n SHALL remain visible in Homepage services
Homepage SHALL include `n8n` in the `Services` group so operators can discover and launch the orchestration surface from the main dashboard.

#### Scenario: Homepage services include n8n
- **WHEN** Homepage `services.yaml` is generated from the repo-managed module
- **THEN** the `Services` group contains an `n8n` entry
- **AND** that entry is associated with the managed `n8n` container on `chill-penguin`
