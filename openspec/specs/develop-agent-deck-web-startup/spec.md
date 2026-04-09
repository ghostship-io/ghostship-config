## ADDED Requirements

### Requirement: WSL develop hosts define and verify background startup for agent-deck web
The repo SHALL define the supported background startup behavior for `agent-deck web` on WSL develop hosts through a user-scoped service, and the resulting behavior SHALL be verified live and documented as part of the supported `agent-deck` workflow.

#### Scenario: Startup behavior is encoded declaratively
- **WHEN** the WSL develop-host configuration is inspected after the change
- **THEN** it SHALL define the supported `agent-deck web` user-service startup behavior declaratively

#### Scenario: User service starts successfully
- **WHEN** the configured WSL develop-host `agent-deck web` user service is started after deployment
- **THEN** it SHALL reach a healthy running state

#### Scenario: Web endpoint is reachable
- **WHEN** the configured `agent-deck web` service is running on a WSL develop host
- **THEN** its web endpoint SHALL be reachable at the configured listen address and port

#### Scenario: Startup scope is documented
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL describe that `agent-deck web` starts automatically on supported WSL develop hosts and under what scope or conditions
