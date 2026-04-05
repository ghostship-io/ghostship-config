# agent-launcher-defaults Specification

## Purpose
Define explicit default approval behavior for the active develop-host CLI launchers.

## Requirements

### Requirement: Develop-host agent launchers declare explicit approval defaults
The repo SHALL configure the active develop-host CLI launchers with explicit approval defaults rather than relying on upstream interactive or permissive defaults.

#### Scenario: Codex config declares approval and sandbox defaults
- **WHEN** the generated `codex/config.toml` is inspected
- **THEN** it SHALL set `approval_policy = "never"` and `sandbox_mode = "danger-full-access"`

#### Scenario: Gemini launcher injects YOLO approval mode by default
- **WHEN** the `gemini` launcher implementation is inspected
- **THEN** it SHALL prepend `--yolo` when the caller did not pass an explicit
  approval-mode flag

#### Scenario: OpenCode system config declares allow-all permissions
- **WHEN** the generated system `opencode/opencode.json` is inspected
- **THEN** it SHALL set `permission` to `"allow"`

#### Scenario: OpenCode Home Manager config declares allow-all permissions
- **WHEN** the generated Home Manager `.config/opencode/opencode.json` file is inspected
- **THEN** it SHALL set `permission` to `"allow"`

### Requirement: Gemini launcher default remains overridable by explicit caller flags
The repo SHALL apply Gemini's default YOLO behavior in the launcher script so the generated `settings.json` remains schema-valid while explicit caller-supplied approval flags still override the default.

#### Scenario: Explicit Gemini approval flags override the default wrapper flag
- **WHEN** the `gemini` launcher receives `--yolo`, `-y`, `--approval-mode=yolo`,
  `--approval-mode default`, `--approval-mode auto_edit`, or `--approval-mode plan`
- **THEN** it SHALL not prepend an additional `--yolo` argument

### Requirement: OpenCode SHALL load its OpenRouter model list from a wrapper-managed generated config
The repo SHALL stop embedding static OpenRouter models in the Nix-managed OpenCode config files and SHALL load the OpenRouter model list for OpenCode from a wrapper-managed generated config selected at launch time.

#### Scenario: Static OpenCode configs stop embedding OpenRouter models
- **WHEN** the generated system `opencode/opencode.json` and Home Manager `.config/opencode/opencode.json` files are inspected
- **THEN** they SHALL not declare a static `provider.openrouter.models` map

#### Scenario: OpenCode wrapper points to the generated config
- **WHEN** the OpenCode launcher starts
- **THEN** it SHALL export `OPENCODE_CONFIG` pointing to the wrapper-managed generated config before executing `opencode-ai`

### Requirement: OpenCode SHALL preserve explicit allow-all permission defaults while using dynamic model config
The repo SHALL preserve explicit OpenCode allow-all permission defaults even after moving model selection out of the static Nix-managed OpenCode config files.

#### Scenario: System OpenCode config still declares explicit permission default
- **WHEN** the generated system `opencode/opencode.json` is inspected
- **THEN** it SHALL still set `permission` to `"allow"`

#### Scenario: Home Manager OpenCode config still declares explicit permission default
- **WHEN** the generated Home Manager `.config/opencode/opencode.json` file is inspected
- **THEN** it SHALL still set `permission` to `"allow"`

### Requirement: Active documentation reflects the launcher risk profile
The repo SHALL document that the develop-host `codex`, `gemini`, and `opencode` launchers default to YOLO or allow-all execution and SHALL describe the activation scope for those changes.

#### Scenario: Launcher docs describe the new defaults
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL state that develop-host launcher defaults are explicit YOLO or allow-all behavior for Codex, Gemini, and OpenCode

#### Scenario: Launcher docs describe activation requirements
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL describe that the change takes effect after the relevant NixOS rebuild or Home Manager switch
