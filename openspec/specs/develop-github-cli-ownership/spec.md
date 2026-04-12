# develop-github-cli-ownership Specification

## Purpose
Define how develop hosts provide GitHub CLI as user-scoped tooling without a repo-managed WSL `envfs` fallback path.

## ADDED Requirements

### Requirement: Develop-profile users receive gh through Home Manager
The shared develop profile SHALL expose `gh` through Home Manager so GitHub CLI remains categorized as interactive user tooling rather than part of the shared system baseline.

#### Scenario: Develop profile includes gh
- **WHEN** the shared develop Home Manager package list is inspected after this change
- **THEN** it SHALL include `gh`

#### Scenario: Shared system baseline does not carry gh solely for develop workflows
- **WHEN** the common `environment.systemPackages` baseline is inspected after this change
- **THEN** it SHALL not include `gh` solely to satisfy develop-host GitHub CLI usage

### Requirement: WSL envfs does not declare a gh-specific fallback
WSL develop-host configuration SHALL not add a repo-managed `services.envfs` fallback entry for `/usr/bin/gh`.

#### Scenario: envfs fallback omits gh
- **WHEN** the WSL `services.envfs.extraFallbackPathCommands` configuration is inspected after this change
- **THEN** it SHALL not create a `gh` entry under the fallback output

#### Scenario: General envfs support remains enabled
- **WHEN** the WSL host configuration is inspected after this change
- **THEN** it SHALL still enable `services.envfs` for general FHS compatibility such as `/usr/bin/bash`

### Requirement: Active documentation reflects the narrower gh contract
The repo SHALL document that `gh` is provided through the develop user profile and SHALL not claim that the repo manages a special `/usr/bin/gh` WSL fallback.

#### Scenario: Workflow docs describe gh as user tooling
- **WHEN** active workflow documentation is inspected after this change
- **THEN** it SHALL describe `gh` as develop-profile Home Manager tooling

#### Scenario: Workflow docs stop promising a repo-managed envfs gh path
- **WHEN** active workflow documentation is inspected after this change
- **THEN** it SHALL not state that the repo provides `/usr/bin/gh` through WSL `envfs`
