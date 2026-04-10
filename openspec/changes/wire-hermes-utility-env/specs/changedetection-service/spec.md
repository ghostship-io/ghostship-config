## MODIFIED Requirements

### Requirement: changedetection SHALL use a dedicated default CloakBrowser profile
The Ghostship-managed CloakBrowser bootstrap SHALL create and preserve a
dedicated persistent profile for `changedetection`, and the
`changedetection` service SHALL derive its Playwright CDP endpoint from that
profile instead of from a shared generic browser profile. The same managed
profile inventory MAY also be reused by Hermes to derive profile-specific
browser defaults without requiring the Hermes-facing profiles to be kept
continuously launched.

#### Scenario: Managed profile set is present after bootstrap
- **WHEN** the CloakBrowser startup bootstrap runs against its persistent data
- **THEN** `assistant`, `operations`, `supervisor`, and `Changedetection`
  profiles exist in the manager profile store
- **AND** the legacy `Direct` and `VPN` profiles are not part of the managed
  default profile set anymore

#### Scenario: changedetection receives a profile-backed CDP URL
- **WHEN** the `changedetection` runtime artifacts are generated
- **THEN** `PLAYWRIGHT_DRIVER_URL` points at
  `http://cloakbrowser:8080/api/profiles/<profile-id>/cdp`
- **AND** the `<profile-id>` is resolved from the dedicated `Changedetection`
  profile rather than hard-coded in the repo

#### Scenario: Dedicated profile is launched for browser-backed checks
- **WHEN** the managed `changedetection` service starts with browser-backed
  fetching enabled
- **THEN** the dedicated `Changedetection` CloakBrowser profile is launched as
  part of the managed runtime flow
- **AND** operators do not need to manually start that profile after activation

#### Scenario: Dedicated profile is kept running while the manager is healthy
- **WHEN** the CloakBrowser manager remains healthy after startup
- **THEN** Ghostship periodically rechecks the dedicated `Changedetection`
  profile state
- **AND** Ghostship relaunches that profile if it is stopped while the manager
  itself is still available

#### Scenario: Hermes reuses the managed profile inventory for browser defaults
- **WHEN** the managed Hermes runtime derives default `BROWSER_CDP_URL` values
  for `assistant`, `operations`, and `supervisor`
- **THEN** it MAY resolve those CDP URLs from the same managed CloakBrowser
  profile inventory
- **AND** that reuse SHALL not change the dedicated launch-and-keepalive
  contract that remains specific to `Changedetection`
