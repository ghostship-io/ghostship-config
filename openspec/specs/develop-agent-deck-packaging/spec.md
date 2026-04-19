# develop-agent-deck-packaging Specification

## Purpose
Define how this repo exposes `agent-deck` as managed interactive tooling for develop-profile users.

## Requirements

### Requirement: The repo exposes agent-deck through the managed wrapper flow
The repo SHALL define `agent-deck` through the same managed wrapper pattern as the other agent CLIs instead of requiring users to run the upstream installer or `go install` manually.

#### Scenario: Wrapper path is declarative
- **WHEN** the repo-managed `agent-deck` command is inspected
- **THEN** it SHALL resolve through a Nix-managed wrapper script that delegates to the maintained user-local install location

#### Scenario: Maintenance tracks the latest release
- **WHEN** `ghostship-agent-maintenance` refreshes `agent-deck`
- **THEN** it SHALL build from the latest upstream source release selected by the release feed instead of a flake-pinned version
- **AND** it SHALL keep the repo-managed web-mutations patch applied to the built binary

#### Scenario: Manual imperative install is not required
- **WHEN** the managed `agent-deck` installation path is reviewed
- **THEN** users SHALL not need to run the upstream `install.sh` script or `go install` themselves

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
- **THEN** it SHALL describe `agent-deck` as a repo-managed develop-profile tool rather than an imperatively installed binary
- **AND** it SHALL note that the managed latest-release build carries the web-mutations patch

#### Scenario: Changelog records the packaging change
- **WHEN** `CHANGELOG.md` is inspected after the change
- **THEN** it SHALL include an entry describing the supported `agent-deck` packaging return for develop-profile users
