## MODIFIED Requirements

### Requirement: Develop-host agent launchers use lightweight wrappers around installed CLIs
The repo SHALL expose `codex`, `gemini`, `gemini-cli`, and `opencode` as lightweight wrapper scripts that delegate to installed user-local agent CLIs instead of launching each agent through `npx` on every invocation.

#### Scenario: Codex launcher delegates to the installed binary
- **WHEN** the generated `codex` launcher is inspected
- **THEN** it SHALL exec the installed user-local `codex` binary rather than `npx -y @openai/codex`

#### Scenario: Gemini launcher delegates to the installed binary
- **WHEN** the generated `gemini` launcher is inspected
- **THEN** it SHALL exec the installed user-local `gemini` binary rather than `npx -y @google/gemini-cli`

#### Scenario: Gemini CLI compatibility launcher delegates to the installed binary
- **WHEN** the generated `gemini-cli` launcher is inspected
- **THEN** it SHALL exec the installed user-local `gemini` binary rather than requiring a shell alias or `npx -y @google/gemini-cli`

#### Scenario: OpenCode launcher delegates to the installed binary
- **WHEN** the generated `opencode` launcher is inspected
- **THEN** it SHALL exec the installed user-local `opencode` binary rather than `npx -y opencode-ai`
