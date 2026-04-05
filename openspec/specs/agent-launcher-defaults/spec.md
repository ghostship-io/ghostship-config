# agent-launcher-defaults Specification

## Purpose
Define explicit default approval behavior for the active develop-host CLI launchers.

## Requirements

### Requirement: Develop-host agent launchers use lightweight wrappers around installed CLIs
The repo SHALL expose `codex`, `gemini`, and `opencode` as lightweight wrapper scripts that delegate to installed user-local agent CLIs instead of launching each agent through `npx` on every invocation.

#### Scenario: Codex launcher delegates to the installed binary
- **WHEN** the generated `codex` launcher is inspected
- **THEN** it SHALL exec the installed user-local `codex` binary rather than `npx -y @openai/codex`

#### Scenario: Gemini launcher delegates to the installed binary
- **WHEN** the generated `gemini` launcher is inspected
- **THEN** it SHALL exec the installed user-local `gemini` binary rather than `npx -y @google/gemini-cli`

#### Scenario: OpenCode launcher delegates to the installed binary
- **WHEN** the generated `opencode` launcher is inspected
- **THEN** it SHALL exec the installed user-local `opencode` binary rather than `npx -y opencode-ai`

### Requirement: Codex launcher defaults to dangerous no-approval mode unless explicitly overridden
The repo SHALL apply Codex's true YOLO default in the launcher script so it prepends the dangerous bypass flag only when the caller did not choose an explicit approval or sandbox mode.

#### Scenario: Codex launcher injects the dangerous bypass flag by default
- **WHEN** the `codex` launcher is invoked without explicit approval, sandbox, `--full-auto`, or dangerous-bypass flags
- **THEN** it SHALL prepend `--dangerously-bypass-approvals-and-sandbox`

#### Scenario: Explicit Codex approval or sandbox flags override the default wrapper flag
- **WHEN** the `codex` launcher receives `-a`, `--ask-for-approval`, `-s`, `--sandbox`, `--full-auto`, or `--dangerously-bypass-approvals-and-sandbox`
- **THEN** it SHALL not prepend an additional dangerous bypass flag

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

### Requirement: OpenCode config keeps explicit allow-all permissions without embedding static OpenRouter models
The repo SHALL stop embedding static OpenRouter models in the Nix-managed OpenCode config files and SHALL keep OpenCode's allow-all default explicit in the generated config paths.

#### Scenario: Static OpenCode configs stop embedding OpenRouter models
- **WHEN** the generated system `opencode/opencode.json` and Home Manager `.config/opencode/opencode.json` files are inspected
- **THEN** they SHALL not declare a static `provider.openrouter.models` map

#### Scenario: System OpenCode config still declares explicit permission default
- **WHEN** the generated system `opencode/opencode.json` is inspected
- **THEN** it SHALL still set `permission` to `"allow"`

#### Scenario: Home Manager OpenCode config still declares explicit permission default
- **WHEN** the generated Home Manager `.config/opencode/opencode.json` file is inspected
- **THEN** it SHALL still set `permission` to `"allow"`

### Requirement: Active documentation reflects the launcher risk profile
The repo SHALL document that the develop-host `codex`, `gemini`, and `opencode` launchers default to YOLO or allow-all execution, that automatic maintenance runs through a systemd timer instead of launch-time wrapper hooks, and that the change takes effect after the relevant rebuild or switch.

#### Scenario: Launcher docs describe the new defaults
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL state that develop-host launcher defaults are explicit YOLO or allow-all behavior for Codex, Gemini, and OpenCode

#### Scenario: Launcher docs describe scheduled maintenance
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL state that agent CLI updates, shared skill refresh, Gemini extension refresh, `agent-browser` bootstrap, and OpenCode model refresh happen through the scheduled maintenance service rather than on each launcher start

#### Scenario: Launcher docs describe activation requirements
- **WHEN** active workflow documentation is inspected
- **THEN** it SHALL describe that the change takes effect after the relevant NixOS rebuild or Home Manager switch
