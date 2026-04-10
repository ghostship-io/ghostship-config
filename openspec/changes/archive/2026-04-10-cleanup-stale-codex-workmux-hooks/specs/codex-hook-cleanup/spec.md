## ADDED Requirements

### Requirement: Develop hosts remove stale Codex hook commands for repo-removed tooling
Develop-host convergence SHALL detect and remove stale Codex hook command entries in `~/.codex/hooks.json` when they match repo-removed managed tooling commands such as the historical `workmux set-window-status ...` hooks.

#### Scenario: Stale workmux commands are removed from Codex hooks
- **WHEN** develop-host cleanup runs on a host where `~/.codex/hooks.json` contains `workmux set-window-status working` or `workmux set-window-status done` command hook entries
- **THEN** the resulting hook file SHALL no longer contain those stale command entries

#### Scenario: Unrelated hook content is preserved
- **WHEN** develop-host cleanup runs on a host where `~/.codex/hooks.json` contains both stale `workmux` command entries and unrelated valid hook entries
- **THEN** it SHALL remove only the stale managed `workmux set-window-status ...` commands and SHALL preserve the unrelated valid hook entries

### Requirement: Stale Codex hook cleanup is safe when hook groups become empty
The repo SHALL treat empty hook groups produced by stale-command cleanup as a valid converged state and SHALL not require the removed command entries to remain present just to preserve object shape.

#### Scenario: Cleanup leaves an event with no remaining hooks
- **WHEN** stale-command cleanup removes the only command entries from a Codex hook event group
- **THEN** the resulting host state SHALL still be considered converged as long as the stale commands no longer execute

#### Scenario: Cleanup does not reintroduce removed commands
- **WHEN** a later develop-host rebuild or switch runs after stale Codex hook entries were removed
- **THEN** the repo-managed convergence path SHALL not recreate the removed `workmux set-window-status ...` commands
