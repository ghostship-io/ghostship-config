# develop-agent-deck-web-startup Specification

## Purpose
Define the supported background startup behavior for `agent-deck web` on WSL develop hosts.

## Requirements

### Requirement: WSL develop hosts define background startup for agent-deck web
The repo SHALL define the supported background startup behavior for `agent-deck web` on WSL develop hosts through a user-scoped service for the `nixos` user.

#### Scenario: Startup behavior is encoded declaratively
- **WHEN** the WSL develop-host configuration is inspected after the change
- **THEN** it SHALL define the supported `agent-deck web` user-service startup behavior declaratively

#### Scenario: Startup stays user-scoped
- **WHEN** the generated systemd unit for `agent-deck web` is inspected
- **THEN** it SHALL be a `systemd --user` service rather than a system service

### Requirement: The supported web endpoint is localhost-only by default
The repo SHALL run `agent-deck web` on WSL develop hosts with the upstream localhost listen address unless a later change explicitly broadens the exposure.

#### Scenario: Listen address matches the supported default
- **WHEN** the configured WSL develop-host `agent-deck web` service is inspected
- **THEN** it SHALL run `agent-deck web --listen 127.0.0.1:8420`

#### Scenario: Endpoint is documented
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL describe the supported WSL `agent-deck web` endpoint as `http://127.0.0.1:8420`

### Requirement: Startup scope is documented
The repo SHALL document that automatic `agent-deck web` startup is supported on WSL develop hosts only.

#### Scenario: Documentation narrows startup scope
- **WHEN** active develop workflow documentation is inspected after the change
- **THEN** it SHALL state that automatic `agent-deck web` startup applies to WSL develop hosts, not all develop hosts
