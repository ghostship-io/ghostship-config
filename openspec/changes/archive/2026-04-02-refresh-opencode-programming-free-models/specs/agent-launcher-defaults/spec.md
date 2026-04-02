## ADDED Requirements

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
