## ADDED Requirements

### Requirement: Scheduled updates tolerate container-level restart failures
The self-hosted Podman update service SHALL use native `podman auto-update`
behavior and SHALL treat container-level restart failures as partial failures
when Podman returns structured per-unit update results.

#### Scenario: One updated container fails to restart
- **WHEN** the scheduled updater runs and Podman reports at least one unit with
  `Updated = failed` while also returning structured results for the run
- **THEN** the updater SHALL log the failed unit names
- **THEN** the updater SHALL exit successfully instead of failing the shared
  `podman-auto-update.service`

### Requirement: Hard updater failures remain fatal
The self-hosted Podman update service SHALL fail the shared update unit when it
cannot obtain trustworthy update results from Podman.

#### Scenario: Registry or command failure prevents trustworthy results
- **WHEN** `podman auto-update` exits nonzero and does not return parseable
  structured results for the run
- **THEN** the updater SHALL preserve a nonzero service result
- **THEN** the failure SHALL remain visible through systemd and journald as a
  real updater failure

### Requirement: Partial failures remain visible in logs
The self-hosted Podman update service SHALL emit a concise warning summary for
units that fail during an otherwise successful update run.

#### Scenario: Partial failure summary is recorded
- **WHEN** one or more units report `Updated = failed` during a scheduled run
- **THEN** the updater SHALL write a warning to journald that identifies the
  failed units
- **THEN** operators SHALL be able to distinguish partial container failures
  from command-level updater failures by reading the service logs

### Requirement: Auto-update runs in the 04:00 randomized window
The self-hosted Podman auto-update timer SHALL schedule runs at `04:00` local
time and SHALL retain the existing 30-minute randomized delay window and
persistent catch-up behavior.

#### Scenario: Normal daily schedule
- **WHEN** the timer is active on a normal day
- **THEN** systemd SHALL schedule the updater to start between `04:00` and
  `04:30` local time

#### Scenario: Missed run catches up after downtime
- **WHEN** the host is down during the scheduled update window and later boots
- **THEN** the timer SHALL trigger a catch-up run because persistent timer
  behavior remains enabled
