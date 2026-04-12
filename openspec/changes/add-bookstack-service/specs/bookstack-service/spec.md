## ADDED Requirements

### Requirement: Ghostship SHALL deploy BookStack as a repo-managed self-hosted service
The self-hosted server stack SHALL declare BookStack as a managed Podman service with durable application state, repo-managed runtime configuration, and a repo-managed database dependency suitable for host rebuilds and service restarts.

#### Scenario: Host configuration emits BookStack and its backing database
- **WHEN** the self-hosted host configuration is evaluated
- **THEN** it includes a BookStack application service and a backing database service in the repo-managed module inventory
- **AND** both services attach to the shared Ghostship container network

#### Scenario: BookStack keeps durable state across activation
- **WHEN** the host activates the BookStack stack
- **THEN** the generated configuration provisions persistent state directories for the BookStack application and its database
- **AND** the service configuration mounts those state paths into the managed containers

### Requirement: Ghostship SHALL project the agreed BookStack env surface
The repo SHALL provide declarative secret wiring and runtime configuration for BookStack using the agreed env names `BOOKSTACK_APP_KEY`, `BOOKSTACK_APP_URL`, `BOOKSTACK_DB_DATABASE`, `BOOKSTACK_DB_USER`, `BOOKSTACK_DB_PASS`, and `BOOKSTACK_DB_ROOT_PASS`.

#### Scenario: Host activation generates BookStack runtime configuration
- **WHEN** the host activation or service pre-start flow runs with the required secret bundle available
- **THEN** it writes the BookStack runtime environment expected by the application and database services using the agreed env names
- **AND** the generated secret material is stored with restrictive permissions suitable for service use

#### Scenario: BookStack configuration uses the external canonical URL
- **WHEN** the BookStack service starts from the repo-managed configuration
- **THEN** `BOOKSTACK_APP_URL` points at the intended external deployment endpoint
- **AND** the database configuration points at the managed internal database dependency

### Requirement: Hermes SHALL receive the BookStack endpoint and token pair
The repo-managed Hermes runtime contract SHALL expose `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET` so Hermes can talk to the BookStack API using the native `Authorization: Token <token_id>:<token_secret>` scheme.

#### Scenario: Hermes static service env includes the BookStack URL
- **WHEN** the Hermes container definition is evaluated after this change
- **THEN** it includes `BOOKSTACK_URL`
- **AND** `BOOKSTACK_URL` points at `https://bookstack.ghostship.io`

#### Scenario: Hermes runtime env includes the BookStack token pair
- **WHEN** the Hermes runtime env projection runs with the BookStack secret bundle available
- **THEN** it projects `BOOKSTACK_TOKEN_ID` and `BOOKSTACK_TOKEN_SECRET` into the Hermes runtime env
- **AND** it does not require a duplicate Hermes-only BookStack secret bundle

### Requirement: Ghostship SHALL preserve manual BookStack bootstrap steps
The repo-managed BookStack deployment SHALL stop short of automating first-run application setup and API token creation, leaving those steps to the operator after the service comes up.

#### Scenario: Apply notes describe the required manual steps
- **WHEN** the BookStack change is prepared for deployment
- **THEN** the rollout guidance includes manual initial BookStack setup and API token creation
- **AND** the repo-managed service contract does not require automatic API token provisioning

### Requirement: Homepage SHALL list BookStack under Services
Homepage SHALL surface BookStack in the `Services` group so operators can reach it alongside the rest of the self-hosted utilities.

#### Scenario: Homepage service generation emits BookStack in Services
- **WHEN** Homepage services configuration is generated from the repo-managed module
- **THEN** the `Services` group includes a BookStack entry
- **AND** the entry identifies the BookStack container and service endpoint
