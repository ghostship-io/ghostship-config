## ADDED Requirements

### Requirement: Managed agent-deck packaging remains independent of WSL web startup
The repo SHALL keep `agent-deck` available as managed interactive tooling for develop-profile users even when no automatic WSL `agent-deck web` background service is defined.

#### Scenario: Develop profile still includes agent-deck without the WSL web service
- **WHEN** the shared develop Home Manager package list is inspected after this change
- **THEN** it SHALL still include `agent-deck`

#### Scenario: Active documentation does not imply automatic WSL web startup
- **WHEN** active develop workflow documentation is inspected after this change
- **THEN** it SHALL describe `agent-deck` as managed develop-host tooling without stating that WSL develop hosts automatically start `agent-deck web`
