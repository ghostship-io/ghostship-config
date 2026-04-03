## ADDED Requirements

### Requirement: Ghostship SHALL manage changedetection.io as a self-hosted service

The server-host stack SHALL include a declarative `changedetection.io` service
with durable application state, internal Podman networking, and the standard
Ghostship healthcheck and activation flow used for repo-managed services.

#### Scenario: Service module is included in the self-hosted inventory
- **WHEN** the self-hosted module inventory is evaluated for `chill-penguin`
- **THEN** a repo-managed `changedetection.io` container definition is emitted
- **AND** the service stores durable state under `/srv/apps/changedetectionio`

#### Scenario: Service starts on internal networking
- **WHEN** the generated container starts on `chill-penguin`
- **THEN** it joins `ghostship_net`
- **AND** it does not expose a new host port directly

### Requirement: changedetection.io SHALL use a dedicated default CloakBrowser profile

The Ghostship-managed CloakBrowser bootstrap SHALL create and preserve a
dedicated persistent profile for `changedetection.io`, and the
`changedetection.io` service SHALL derive its Playwright CDP endpoint from that
profile instead of from a shared generic browser profile.

#### Scenario: Dedicated profile is present after bootstrap
- **WHEN** the CloakBrowser startup bootstrap runs against its persistent data
- **THEN** a `Changedetection` profile exists in the manager profile store
- **AND** the existing `Direct` and `VPN` profiles remain intact

#### Scenario: changedetection.io receives a profile-backed CDP URL
- **WHEN** the `changedetection.io` runtime artifacts are generated
- **THEN** `PLAYWRIGHT_DRIVER_URL` points at
  `http://cloakbrowser:8080/api/profiles/<profile-id>/cdp`
- **AND** the `<profile-id>` is resolved from the dedicated `Changedetection`
  profile rather than hard-coded in the repo

#### Scenario: Dedicated profile is launched for browser-backed checks
- **WHEN** the managed `changedetection.io` service starts with browser-backed
  fetching enabled
- **THEN** the dedicated `Changedetection` CloakBrowser profile is launched as
  part of the managed runtime flow
- **AND** operators do not need to manually start that profile after activation

### Requirement: changedetection.io SHALL be visible in Homepage services

Homepage SHALL include `Changedetection` in the `Services` group so the new
stack component is visible alongside the other self-hosted application tiles.

#### Scenario: Homepage services include Changedetection
- **WHEN** Homepage `services.yaml` is generated from the repo-managed module
- **THEN** the `Services` group includes a `Changedetection` entry
- **AND** that entry points at the managed `changedetection.io` container
