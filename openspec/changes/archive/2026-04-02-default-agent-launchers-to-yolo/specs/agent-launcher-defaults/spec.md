## ADDED Requirements

### Requirement: Develop-host agent launchers declare explicit approval defaults
The repo SHALL configure the active develop-host CLI launchers with explicit approval defaults rather than relying on upstream interactive or permissive defaults.

#### Scenario: Codex config declares approval and sandbox defaults
- **WHEN** the generated `codex/config.toml` is inspected
- **THEN** it SHALL set `approval_policy = "never"` and `sandbox_mode = "danger-full-access"`

#### Scenario: Gemini config declares YOLO approval mode
- **WHEN** the generated `gemini-cli/settings.json` is inspected
- **THEN** it SHALL set `general.defaultApprovalMode` to `"yolo"`

#### Scenario: OpenCode system config declares allow-all permissions
- **WHEN** the generated system `opencode/opencode.json` is inspected
- **THEN** it SHALL set `permission` to `"allow"`

#### Scenario: OpenCode Home Manager config declares allow-all permissions
- **WHEN** the generated Home Manager `.config/opencode/opencode.json` file is inspected
- **THEN** it SHALL set `permission` to `"allow"`

### Requirement: Launcher defaults remain configurable through native config surfaces
The repo SHALL express the default execution behavior through each CLI's supported config format so explicit caller-supplied CLI flags can still override the defaults.

#### Scenario: Implementation avoids hidden wrapper argument injection
- **WHEN** the develop launcher implementation is inspected
- **THEN** the YOLO defaults SHALL be set in generated TOML or JSON config files rather than by prepending hidden CLI arguments in the wrapper script

### Requirement: Active documentation reflects the launcher risk profile
The repo SHALL document that the develop-host `codex`, `gemini`, and `opencode` launchers default to YOLO or allow-all execution and SHALL describe the activation scope for those changes.

#### Scenario: Launcher docs describe the new defaults
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL state that develop-host launcher defaults are explicit YOLO or allow-all behavior for Codex, Gemini, and OpenCode

#### Scenario: Launcher docs describe activation requirements
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL describe that the change takes effect after the relevant NixOS rebuild or Home Manager switch
