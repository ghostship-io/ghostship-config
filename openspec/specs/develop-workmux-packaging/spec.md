# develop-workmux-packaging Specification

## Purpose
Define how this repo packages and exposes `workmux` as declarative interactive
tooling for develop-profile users.

## ADDED Requirements

### Requirement: The repo packages workmux as a Nix-managed develop tool
The repo SHALL define `workmux` as a Nix-managed package from a pinned upstream
source instead of requiring users to install it with upstream's installer
script or `cargo install`.

#### Scenario: Package source is declarative
- **WHEN** the repo packaging for `workmux` is inspected
- **THEN** it SHALL fetch or pin the upstream source declaratively and build or
  expose the `workmux` CLI through Nix

#### Scenario: Package does not depend on imperative bootstrap
- **WHEN** the managed `workmux` installation path is reviewed
- **THEN** it SHALL not require the upstream install script or a user-run
  `cargo install workmux` command

### Requirement: Develop-profile users receive workmux through Home Manager
The shared develop profile SHALL expose `workmux` through Home Manager so the
CLI is available as interactive user tooling on develop hosts without extending
the server-host baseline package set.

#### Scenario: Develop profile includes workmux
- **WHEN** the shared develop Home Manager package list is inspected
- **THEN** it SHALL include `workmux`

#### Scenario: Server baseline is unchanged
- **WHEN** the shared server-safe system package baseline is inspected
- **THEN** it SHALL not add `workmux` as a generic host-wide package solely for
  this change

### Requirement: Develop hosts provide the runtime baseline for the supported workmux workflow
Develop-host configuration SHALL provide the runtime dependencies needed for the
repo-supported `workmux` workflow, including `git` and `tmux`, so the packaged
path works without separate manual prerequisite installation.

#### Scenario: tmux-based runtime is provided declaratively
- **WHEN** the evaluated develop-host package configuration is inspected after
  the change
- **THEN** it SHALL include the declarative `git` and `tmux` runtime baseline
  used for the repo-supported `workmux` workflow

#### Scenario: Supported backend scope is documented
- **WHEN** active documentation for the develop agent workflow is inspected
- **THEN** it SHALL describe the managed `workmux` path as targeting the
  existing `tmux`-based workflow first

### Requirement: Active documentation describes the managed workmux workflow
The repo SHALL document that `workmux` is provided as a repo-managed develop
tool and SHALL record the change in active documentation and changelog entries.

#### Scenario: Workflow docs mention declarative availability
- **WHEN** active develop workflow documentation is inspected
- **THEN** it SHALL describe `workmux` as a Nix-managed develop-profile tool
  rather than an imperatively installed binary

#### Scenario: Activation requirements are documented
- **WHEN** active develop workflow documentation is inspected
- **THEN** it SHALL state that `workmux` becomes available after the relevant
  Home Manager or NixOS rebuild/switch

#### Scenario: Changelog records the packaging change
- **WHEN** `CHANGELOG.md` is inspected after the change
- **THEN** it SHALL include an entry describing the addition of repo-managed
  `workmux` packaging for develop-profile users
