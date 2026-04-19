## ADDED Requirements

### Requirement: WSL envfs keeps Linux FHS compatibility without importing Windows PATH executables
WSL hosts SHALL keep `services.envfs` enabled for Linux/FHS compatibility and SHALL disable automatic Windows PATH import so `envfs` does not synthesize Windows executables from imported PATH entries.

#### Scenario: WSL host configuration is inspected
- **WHEN** the WSL host module configuration is inspected
- **THEN** it SHALL enable `services.envfs`
- **AND** it SHALL set `wsl.wslConf.interop.appendWindowsPath = false`

### Requirement: WSL open flow uses explicit Windows PowerShell path
The repo SHALL provide `wsl-open` through a wrapper that uses the real Windows PowerShell executable path instead of resolving `powershell.exe` from PATH.

#### Scenario: WSL open command is inspected
- **WHEN** the repo-managed `wsl-open` command is invoked in the WSL profile
- **THEN** it SHALL launch through `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`
- **AND** it SHALL not depend on `command -v powershell.exe`

### Requirement: Supported Windows tools use explicit repo-managed entrypoints
The repo SHALL document and expose supported Windows tools on WSL through explicit paths or wrappers rather than relying on Windows PATH import into the Linux shell environment.

#### Scenario: Operator needs Windows PowerShell on WSL
- **WHEN** an operator uses the repo-managed PowerShell entrypoint on a WSL host
- **THEN** the entrypoint SHALL execute the real Windows PowerShell binary by explicit path
- **AND** the documented workflow SHALL not require bare `powershell.exe` from PATH

### Requirement: WSL docs describe explicit Windows interop contract
The repo SHALL document that WSL hosts keep `envfs` for Linux/FHS paths and use explicit wrappers or explicit Windows paths for supported Windows tools.

#### Scenario: WSL workflow docs are inspected
- **WHEN** README, AGENTS memory, or WSL skill references are inspected after this change
- **THEN** they SHALL describe `envfs` as Linux/FHS compatibility support
- **AND** they SHALL not imply that imported Windows PATH commands like bare `powershell.exe` are part of the supported repo contract
