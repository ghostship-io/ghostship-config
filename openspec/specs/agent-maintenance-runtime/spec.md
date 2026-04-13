# agent-maintenance-runtime Specification

## Purpose
Define the runtime guarantees required by the develop-host `ghostship-agent-maintenance` service.

## Requirements

### Requirement: Agent maintenance SHALL provide a shell-capable runtime for npm and npx subprocesses
The develop-host `ghostship-agent-maintenance` service SHALL explicitly provide the runtime tools that npm- and npx-driven child processes require under systemd, including an executable POSIX shell in the service command environment.

#### Scenario: Maintenance runtime exposes a shell command to npm child processes
- **WHEN** the generated `ghostship-agent-maintenance` service or script environment is inspected
- **THEN** it SHALL provide an executable `sh` command in the runtime path used for npm and npx subprocesses

#### Scenario: Maintenance refresh steps do not fail with missing-shell subprocess errors
- **WHEN** `ghostship-agent-maintenance` runs npm- or npx-based refresh steps on a develop host
- **THEN** those steps SHALL not fail with `spawn sh ENOENT`

### Requirement: Agent maintenance SHALL preserve the managed user-local agent tool layout
The develop-host `ghostship-agent-maintenance` service SHALL continue running its CLI refreshes against the managed user-local agent tools home so launcher wrappers and scheduled upkeep operate on the same installed binaries.

#### Scenario: Maintenance writes into the managed agent npm prefix
- **WHEN** the generated maintenance environment is inspected
- **THEN** it SHALL target `/home/nixos/.local/share/ghostship-agent-tools/npm` as the npm prefix used for managed agent CLI installs

#### Scenario: Managed OpenSpec wrapper and maintenance share the same installed binary
- **WHEN** the managed `openspec` wrapper and the maintenance environment are inspected together
- **THEN** they SHALL both resolve OpenSpec from the managed user-local agent tools prefix rather than from unrelated global npm state once maintenance has installed it there

#### Scenario: Managed Gemini launcher and maintenance share the same installed binary
- **WHEN** the managed `gemini` launcher and the maintenance environment are inspected together
- **THEN** they SHALL both resolve Gemini from the managed user-local agent tools prefix rather than from unrelated global npm state

### Requirement: Agent maintenance SHALL enforce the configured external agent asset set
The develop-host `ghostship-agent-maintenance` service SHALL ensure the repo-configured external `skills.sh` repositories and Gemini extensions are installed, then refresh them during scheduled upkeep so new WSL develop hosts converge without manual agent bootstrapping.

#### Scenario: Managed skills.sh repositories are installed globally when missing
- **WHEN** a develop host runs maintenance without the configured managed `skills.sh` repo installs present
- **THEN** maintenance SHALL install those repos globally before the refresh step

#### Scenario: Installed global skills continue to refresh after managed installs converge
- **WHEN** `ghostship-agent-maintenance` runs after the configured managed global `skills.sh` repos are already installed
- **THEN** it SHALL still run the global skill refresh flow instead of skipping updates

#### Scenario: Managed Gemini extensions are installed or updated during upkeep
- **WHEN** `ghostship-agent-maintenance` runs on a develop host
- **THEN** it SHALL install missing configured Gemini extensions and update already-installed configured Gemini extensions
