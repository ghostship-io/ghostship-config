# develop-agent-deck-web-startup Specification

## Purpose
Define the supported WSL behavior for `agent-deck web` on develop hosts.

## Requirements

### Requirement: WSL develop hosts do not define background startup for agent-deck web
The repo SHALL NOT define a managed background startup path for `agent-deck web` on WSL develop hosts.

#### Scenario: Startup behavior is not encoded declaratively
- **WHEN** the WSL develop-host configuration is inspected
- **THEN** it SHALL NOT define an `agent-deck web` user service

#### Scenario: No generated user service exists
- **WHEN** the generated user units are inspected
- **THEN** they SHALL NOT include `agent-deck-web.service`

### Requirement: No managed web endpoint is documented
The repo SHALL NOT document a repo-managed WSL web endpoint for `agent-deck web`.

#### Scenario: Endpoint is not documented
- **WHEN** active develop workflow documentation is inspected
- **THEN** it SHALL NOT describe a supported WSL `agent-deck web` endpoint

### Requirement: Startup scope is documented
The repo SHALL document that automatic `agent-deck web` startup is not provided on WSL develop hosts.

#### Scenario: Documentation narrows startup scope
- **WHEN** active develop workflow documentation is inspected
- **THEN** it SHALL state that automatic `agent-deck web` startup is not supported declaratively
