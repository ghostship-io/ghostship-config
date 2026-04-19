## ADDED Requirements

### Requirement: The repo exposes paseo through the managed wrapper flow
The repo SHALL define `paseo` through the same managed wrapper pattern used for the other agent CLIs so develop hosts do not require a separate manual Paseo install.

#### Scenario: Wrapper path is declarative
- **WHEN** the repo-managed `paseo` command is inspected
- **THEN** it SHALL resolve through a Nix-managed wrapper script that delegates to the maintained user-local install location

#### Scenario: Manual install is not required
- **WHEN** the managed `paseo` installation path is reviewed
- **THEN** users SHALL not need to run `npm install -g @getpaseo/cli` manually for the supported repo workflow

### Requirement: Agent maintenance refreshes paseo automatically
The develop-host `ghostship-agent-maintenance` service SHALL install and refresh `@getpaseo/cli` alongside the other managed agent CLIs.

#### Scenario: Maintenance installs paseo into the managed npm prefix
- **WHEN** `ghostship-agent-maintenance` runs on a host without a managed Paseo install yet
- **THEN** it SHALL install `@getpaseo/cli` into `/home/nixos/.local/share/ghostship-agent-tools/npm`

#### Scenario: Maintenance updates paseo during scheduled upkeep
- **WHEN** `ghostship-agent-maintenance` runs after Paseo is already installed
- **THEN** it SHALL refresh the managed Paseo CLI instead of leaving it static

### Requirement: Active docs describe the managed paseo workflow
The repo SHALL document that `paseo` is a managed develop-host tool provided through the shared wrapper and maintenance flow.

#### Scenario: Workflow docs mention declarative availability
- **WHEN** active develop workflow documentation is inspected
- **THEN** it SHALL describe `paseo` as repo-managed tooling that becomes available after the relevant rebuild or switch
