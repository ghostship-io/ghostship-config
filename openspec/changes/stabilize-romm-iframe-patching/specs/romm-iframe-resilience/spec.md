## ADDED Requirements

### Requirement: RomM upgrades SHALL be validated without stale iframe patches
The RomM service workflow SHALL verify whether a newly updated upstream RomM
image still reproduces the iframe regression before the repo keeps or replaces
an iframe-specific mitigation.

#### Scenario: Unpatched image no longer reproduces the regression
- **WHEN** the current RomM image is started without the repo iframe patch
- **THEN** the validation flow SHALL record that no iframe mitigation is needed
- **AND** the service definition SHALL be allowed to start without a patch

#### Scenario: Unpatched image still reproduces the regression
- **WHEN** the current RomM image is started without the repo iframe patch
- **THEN** the validation flow SHALL record that the iframe regression still
  exists
- **AND** the service definition SHALL require a mitigation before the change is
  considered complete

### Requirement: Required iframe mitigation SHALL survive routine upstream updates
If RomM still needs an iframe workaround, the mitigation SHALL avoid depending
on a specific hashed asset filename or one exact minified bundle string so that
routine upstream frontend rebuilds do not break service startup.

#### Scenario: Upstream rebuild changes bundle hash
- **WHEN** RomM ships a new frontend bundle hash without changing the effective
  iframe mitigation strategy
- **THEN** the host SHALL still be able to apply the mitigation or safely no-op
  without failing service startup

#### Scenario: Mitigation is already applied or no longer needed
- **WHEN** the host starts RomM and the mitigation target state is already
  satisfied
- **THEN** the startup logic SHALL exit successfully rather than failing on a
  missing old patch target

### Requirement: RomM startup failures SHALL identify the failing stage
The RomM host workflow SHALL distinguish validation failures, mitigation
application failures, and application runtime failures so operators can tell
whether the issue is the iframe workaround or RomM itself.

#### Scenario: Validation fails before mitigation choice is known
- **WHEN** the host cannot complete the unpatched iframe validation step
- **THEN** the reported failure SHALL identify validation as the failing stage

#### Scenario: Mitigation application fails
- **WHEN** the host determines a mitigation is needed but cannot apply it
- **THEN** the reported failure SHALL identify mitigation application as the
  failing stage
