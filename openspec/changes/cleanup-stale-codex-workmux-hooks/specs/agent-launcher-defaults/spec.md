## MODIFIED Requirements

### Requirement: Active documentation reflects the launcher risk profile
The repo SHALL document that the develop-host `codex`, `gemini`, and `opencode` launchers default to YOLO or allow-all execution, that automatic maintenance runs through a systemd timer instead of launch-time wrapper hooks, that stale removed-tool Codex hook state is cleaned during managed develop-host convergence, and that the change takes effect after the relevant rebuild or switch.

#### Scenario: Launcher docs describe the new defaults
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL state that develop-host launcher defaults are explicit YOLO or allow-all behavior for Codex, Gemini, and OpenCode

#### Scenario: Launcher docs describe scheduled maintenance
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL state that agent CLI updates, shared skill refresh, Gemini extension refresh, `agent-browser` bootstrap, and OpenCode model refresh happen through the scheduled maintenance service rather than on each launcher start

#### Scenario: Launcher docs describe stale hook cleanup behavior
- **WHEN** active workflow documentation is inspected after this change
- **THEN** it SHALL state that managed develop-host convergence cleans stale Codex hook entries for removed repo-managed tooling and that already-running Codex or Agent Deck sessions may need a restart to observe the cleaned state

#### Scenario: Launcher docs describe activation requirements
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL describe that the change takes effect after the relevant NixOS rebuild or Home Manager switch
