# develop-agent-deck-packaging Specification

## Purpose
Define how this repo packages and exposes `agent-deck` as declarative interactive tooling for develop-profile users.

## ADDED Requirements

### Requirement: The repo packages agent-deck as a Nix-managed develop tool
The repo SHALL define `agent-deck` as a Nix-managed package sourced from an upstream tagged release instead of requiring users to install it with the upstream shell installer or `go install`.

#### Scenario: Package source is declarative
- **WHEN** the repo packaging for `agent-deck` is inspected
- **THEN** it SHALL fetch the upstream source from a pinned tagged release and build the `agent-deck` CLI through Nix

#### Scenario: Package does not depend on imperative bootstrap
- **WHEN** the managed `agent-deck` installation path is reviewed
- **THEN** it SHALL not require the upstream `install.sh` script or a user-run `go install` command

### Requirement: Develop-profile users receive agent-deck through Home Manager
The shared develop profile SHALL expose `agent-deck` through Home Manager so the CLI is available as interactive user tooling on develop hosts without extending the server-host baseline package set.

#### Scenario: Develop profile includes agent-deck
- **WHEN** the shared develop Home Manager package list is inspected
- **THEN** it SHALL include `agent-deck`

#### Scenario: Server baseline is unchanged
- **WHEN** the shared server-safe system package baseline is inspected
- **THEN** it SHALL not add `agent-deck` as a generic host-wide package solely for this change

### Requirement: Develop hosts provide required runtime dependencies for agent-deck
Develop-host configuration SHALL provide the runtime dependencies needed for normal `agent-deck` operation, including `tmux`, so the packaged workflow works without separate manual prerequisite installation.

#### Scenario: tmux is provided declaratively
- **WHEN** the evaluated develop-host package configuration is inspected after the change
- **THEN** it SHALL include `tmux` in the declarative host configuration used with `agent-deck`

#### Scenario: Activation requirements are documented
- **WHEN** active documentation for the develop agent workflow is inspected
- **THEN** it SHALL state that `agent-deck` becomes available after the relevant Home Manager or NixOS rebuild/switch

### Requirement: Active documentation describes the managed agent-deck workflow
The repo SHALL document that `agent-deck` is provided as a repo-managed develop tool and SHALL record the change in active documentation and changelog entries.

#### Scenario: Workflow docs mention declarative availability
- **WHEN** active develop workflow documentation is inspected
- **THEN** it SHALL describe `agent-deck` as a Nix-managed develop-profile tool rather than an imperatively installed binary

#### Scenario: Changelog records the packaging change
- **WHEN** `CHANGELOG.md` is inspected after the change
- **THEN** it SHALL include an entry describing the addition of repo-managed `agent-deck` packaging for develop-profile users

### Requirement: Managed agent-deck packaging remains independent of WSL web startup
The repo SHALL keep `agent-deck` available as managed interactive tooling for develop-profile users even when no automatic WSL `agent-deck web` background service is defined.

#### Scenario: Develop profile still includes agent-deck without the WSL web service
- **WHEN** the shared develop Home Manager package list is inspected after this change
- **THEN** it SHALL still include `agent-deck`

#### Scenario: Active documentation does not imply automatic WSL web startup
- **WHEN** active develop workflow documentation is inspected after this change
- **THEN** it SHALL describe `agent-deck` as managed develop-host tooling without stating that WSL develop hosts automatically start `agent-deck web`
