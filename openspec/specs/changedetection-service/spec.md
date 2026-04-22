## MODIFIED Requirements

### Requirement: changedetection SHALL use an embedded CloakBrowser browser path
The Ghostship-managed `changedetection` image SHALL embed the shared CloakBrowser binary contract and SHALL run browser-backed checks through a local CloakBrowser Playwright session instead of a manager-backed CDP profile.

#### Scenario: changedetection image carries the shared browser contract
- **WHEN** the repo-managed changedetection image is built
- **THEN** it SHALL include the CloakBrowser package and binary
- **AND** `CLOAKBROWSER_BINARY_PATH` SHALL point at the embedded browser inside that image

#### Scenario: browser-backed checks no longer require a manager CDP URL
- **WHEN** the `changedetection` service starts after this change
- **THEN** Ghostship SHALL not generate or require `PLAYWRIGHT_DRIVER_URL`
- **AND** the service SHALL not depend on the standalone CloakBrowser manager to launch browser-backed checks

#### Scenario: local Playwright launch uses CloakBrowser humanization
- **WHEN** a changedetection watch uses the browser-backed fetcher
- **THEN** the local Playwright launch SHALL use the embedded CloakBrowser path
- **AND** it SHALL enable `humanize=True`
- **AND** it SHALL keep the default CloakBrowser stealth args enabled

#### Scenario: browser steps continue to work through the local browser path
- **WHEN** the browser steps UI starts a live session for a browser-backed watch
- **THEN** changedetection SHALL open that session through a local CloakBrowser Playwright browser
- **AND** operators SHALL not need a separate remote CDP endpoint for browser steps

#### Scenario: Hermes browser defaults remain independent of changedetection
- **WHEN** the managed Hermes runtime is evaluated after this change
- **THEN** Hermes SHALL not derive default browser connection values from changedetection's embedded browser path
- **AND** the changedetection browser contract SHALL remain specific to changedetection.io
