## ADDED Requirements

### Requirement: WSL develop hosts provide a managed Paseo daemon service
WSL develop-host configuration SHALL define a systemd service for a persistent Paseo daemon so the Windows desktop app can attach to the WSL-hosted instance without manual shell startup after each boot.

#### Scenario: WSL system service is declared
- **WHEN** the WSL develop-host systemd configuration is inspected
- **THEN** it SHALL define a repo-managed Paseo daemon service
- **AND** that service SHALL be enabled through a normal boot target

#### Scenario: Service runs Paseo in the managed user context
- **WHEN** the managed Paseo daemon service definition is inspected
- **THEN** it SHALL run as user `nixos`
- **AND** it SHALL execute the managed `paseo` CLI in foreground mode with the expected home-directory environment

### Requirement: Managed Paseo daemon defaults to a deliberate local listen contract
The repo SHALL define the managed WSL Paseo daemon around an explicit listen and hostname contract suitable for same-machine Windows desktop attachment rather than broad default exposure.

#### Scenario: Service listen arguments are explicit
- **WHEN** the managed Paseo daemon startup command or config is inspected
- **THEN** it SHALL set an explicit listen target for the daemon
- **AND** it SHALL not rely on an unspecified upstream default bind address

#### Scenario: Broad exposure is not the default
- **WHEN** the repo-managed default Paseo daemon contract is reviewed
- **THEN** it SHALL not default to `0.0.0.0` exposure for this WSL desktop-attachment workflow

### Requirement: Active docs describe connection and version expectations
The repo SHALL document how the Windows desktop app connects to the managed WSL Paseo daemon and SHALL call out any upstream daemon/app version-alignment requirement that affects the supported workflow.

#### Scenario: Docs explain the managed desktop attachment flow
- **WHEN** active documentation is inspected after the change
- **THEN** it SHALL describe the supported Windows desktop attachment path for the WSL-hosted Paseo daemon

#### Scenario: Docs mention version lockstep caveat
- **WHEN** the managed Paseo workflow documentation is inspected
- **THEN** it SHALL state that upstream currently expects daemon and app versions to remain aligned
