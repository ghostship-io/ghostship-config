## MODIFIED Requirements

### Requirement: Develop-profile users receive workmux through Home Manager
The shared develop profile SHALL no longer expose `workmux` through Home Manager, and the repo SHALL remove active documentation and support claims that treat it as a managed develop-host tool.

#### Scenario: Develop profile stops including workmux
- **WHEN** the shared develop Home Manager package list is inspected after the change
- **THEN** it SHALL not include `workmux`

#### Scenario: Active docs stop advertising support
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL not describe `workmux` as a repo-managed develop-profile tool

### Requirement: Active documentation describes the managed workmux workflow
The repo SHALL retire the active `workmux` workflow description and SHALL instead record its removal and cleanup in the changelog and removal-related documentation.

#### Scenario: Changelog records removal
- **WHEN** `CHANGELOG.md` is inspected after the change
- **THEN** it SHALL include an entry describing the removal of repo-managed `workmux` support

#### Scenario: Known local artifacts are covered by the removal change
- **WHEN** the removal change documentation or tasks are inspected
- **THEN** they SHALL include deletion of the known `workmux` artifact paths under `/home/nixos`, including the OpenCode plugin and skill files currently tied to `workmux`

## REMOVED Requirements

### Requirement: The repo packages workmux as a Nix-managed develop tool
**Reason**: The repo no longer intends to support `workmux` as a managed develop-host tool.
**Migration**: Remove the local package definition and overlay wiring instead of keeping a pinned upstream source.

### Requirement: Develop hosts provide the runtime baseline for the supported workmux workflow
**Reason**: The repo is no longer maintaining a supported `workmux` workflow path.
**Migration**: Remove repo-managed `workmux` references and cleanup the known local state instead of preserving a supported backend contract.
