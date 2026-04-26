# wsl-envfs-windows-interop Specification

## Purpose
Define the supported WSL contract after removing `envfs`: Windows PATH import is enabled for desktop interop, and Linux compatibility wrappers are added only for observed failures.

## Requirements
### Requirement: WSL removes envfs and imports Windows PATH
WSL hosts SHALL keep `services.envfs` disabled and SHALL enable automatic Windows PATH import.

#### Scenario: WSL host configuration is inspected
- **WHEN** the WSL host module configuration is inspected
- **THEN** it SHALL not enable `services.envfs`
- **AND** it SHALL set `wsl.wslConf.interop.appendWindowsPath = true`

### Requirement: WSL open flow uses explicit Windows PowerShell path
The repo SHALL provide `wsl-open` through a wrapper that uses the real Windows PowerShell executable path instead of resolving `powershell.exe` from PATH.

#### Scenario: WSL open command is inspected
- **WHEN** the repo-managed `wsl-open` command is invoked in the WSL profile
- **THEN** it SHALL launch through `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`
- **AND** it SHALL not depend on `command -v powershell.exe`

### Requirement: Deterministic Windows tool flows keep explicit repo-managed entrypoints
The repo SHALL keep explicit paths or wrappers for Windows flows where deterministic behavior matters, even though Windows PATH import is enabled.

#### Scenario: Operator needs Windows PowerShell on WSL
- **WHEN** an operator uses the repo-managed PowerShell entrypoint on a WSL host
- **THEN** the entrypoint SHALL execute the real Windows PowerShell binary by explicit path
- **AND** the documented deterministic workflow SHALL not require bare `powershell.exe` from PATH

### Requirement: WSL docs describe explicit Windows interop contract
The repo SHALL document that WSL hosts do not use `envfs`, import Windows PATH, and add Linux compatibility wrappers only after observed failures.

#### Scenario: WSL workflow docs are inspected
- **WHEN** README, AGENTS memory, or WSL skill references are inspected after this change
- **THEN** they SHALL describe Windows PATH import as enabled
- **AND** they SHALL describe compatibility wrappers as failure-driven
