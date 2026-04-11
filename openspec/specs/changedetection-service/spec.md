## MODIFIED Requirements

### Requirement: changedetection SHALL use a dedicated default CloakBrowser profile
The Ghostship-managed CloakBrowser bootstrap SHALL create and preserve a dedicated persistent profile for `Changedetection`, and the `changedetection` service SHALL derive its Playwright CDP endpoint from that profile instead of from a shared generic browser profile.

#### Scenario: Managed profile set is present after bootstrap
- **WHEN** the CloakBrowser startup bootstrap runs against its persistent data after this change
- **THEN** the `Changedetection` profile SHALL exist in the manager profile store
- **AND** the repo SHALL not require `assistant`, `operations`, `supervisor`, `Direct`, or `VPN` to remain part of the managed default profile set

#### Scenario: changedetection receives a profile-backed CDP URL
- **WHEN** the `changedetection` runtime artifacts are generated
- **THEN** `PLAYWRIGHT_DRIVER_URL` SHALL point at `http://cloakbrowser:8080/api/profiles/<profile-id>/cdp`
- **AND** the `<profile-id>` SHALL be resolved from the dedicated `Changedetection` profile rather than hard-coded in the repo

#### Scenario: Dedicated profile is launched for browser-backed checks
- **WHEN** the managed `changedetection` service starts with browser-backed fetching enabled
- **THEN** the dedicated `Changedetection` CloakBrowser profile SHALL be launched as part of the managed runtime flow
- **AND** operators SHALL not need to manually start that profile after activation

#### Scenario: Dedicated profile is kept running while the manager is healthy
- **WHEN** the CloakBrowser manager remains healthy after startup
- **THEN** Ghostship SHALL periodically recheck the dedicated `Changedetection` profile state
- **AND** Ghostship SHALL relaunch that profile if it is stopped while the manager itself is still available

#### Scenario: Hermes browser defaults no longer depend on the managed profile inventory
- **WHEN** the managed Hermes runtime is evaluated after this change
- **THEN** Hermes SHALL not derive default browser connection values from the CloakBrowser profile inventory
- **AND** the `Changedetection` profile contract SHALL remain specific to changedetection.io
