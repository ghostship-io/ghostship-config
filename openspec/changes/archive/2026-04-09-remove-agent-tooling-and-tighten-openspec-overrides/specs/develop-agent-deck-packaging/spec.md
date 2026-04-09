## MODIFIED Requirements

### Requirement: The repo packages agent-deck as a Nix-managed develop tool
The repo SHALL continue to define `agent-deck` as a Nix-managed develop tool and SHALL pin it to the latest confirmed upstream release selected by the repo for active support.

#### Scenario: Package pin is updated to the current supported release
- **WHEN** the repo packaging for `agent-deck` is inspected after the change
- **THEN** it SHALL pin `agent-deck` to the latest confirmed upstream release selected for support by this repo, currently `v1.4.1`

#### Scenario: Package remains declarative
- **WHEN** the managed `agent-deck` installation path is reviewed after the change
- **THEN** it SHALL still fetch the upstream source declaratively and build the `agent-deck` CLI through Nix rather than relying on the upstream installer or `go install`

### Requirement: Active documentation describes the managed agent-deck workflow
The repo SHALL continue to document `agent-deck` as a repo-managed develop tool and SHALL record the supported version or behavior changes in active documentation and changelog entries.

#### Scenario: Workflow docs continue to advertise support
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL continue to describe `agent-deck` as a Nix-managed develop-profile tool

#### Scenario: Changelog records the version change
- **WHEN** `CHANGELOG.md` is inspected after the change
- **THEN** it SHALL include an entry describing the `agent-deck` version bump or support change
