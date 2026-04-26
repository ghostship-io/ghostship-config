# wsl-node-package-manager-fhs-wrappers Specification

## Purpose
Define that WSL npm and npx compatibility wrappers are failure-driven rather than installed speculatively.

## Requirements

### Requirement: WSL does not provide speculative npm and npx wrappers
WSL host configuration SHALL not provide repo-managed `npm` and `npx` compatibility wrappers unless a concrete post-envfs-removal failure is observed.

#### Scenario: npm compatibility wrapper is absent by default
- **WHEN** the WSL compatibility wrapper configuration is inspected
- **THEN** it SHALL not add a repo-managed `npm` wrapper

#### Scenario: npx compatibility wrapper is absent by default
- **WHEN** the WSL compatibility wrapper configuration is inspected
- **THEN** it SHALL not add a repo-managed `npx` wrapper

### Requirement: Node package-manager validation uses the managed updater
The repo SHALL validate npm and npx behavior through the managed `ghostship-agent-maintenance` updater before adding replacement wrappers.

#### Scenario: updater validates npm usage
- **WHEN** the envfs removal is applied to a WSL host
- **THEN** `ghostship-agent-maintenance` SHALL complete without npm spawn failures before npm remains wrapper-free

#### Scenario: updater validates npx usage
- **WHEN** the envfs removal is applied to a WSL host
- **THEN** `ghostship-agent-maintenance` SHALL complete without npx spawn failures before npx remains wrapper-free

### Requirement: Docs describe the supported Node package-manager compatibility path
The repo SHALL document that npm and npx wrappers are not added speculatively and were removed after validation showed symlinked raw Node entrypoints work.

#### Scenario: WSL workflow docs mention failure-driven compatibility
- **WHEN** the WSL workflow documentation or repo agent memory is inspected
- **THEN** it SHALL describe npm and npx wrappers as absent by default unless a concrete failure is observed
