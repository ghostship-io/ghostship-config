## ADDED Requirements

### Requirement: Hermes SHALL use Codex as the normal primary model lane
The self-hosted Hermes runtime on `chill-penguin` SHALL treat the current
upstream Codex-primary model contract as the supported default.

#### Scenario: Managed runtime uses Codex primary, OpenCode fallback, and router custom provider
- **WHEN** the refreshed Hermes runtime contract is applied on `chill-penguin`
- **THEN** the supported managed primary model lane SHALL be
  `openai-codex/gpt-5.4`
- **AND** the supported managed fallback model lane SHALL be
  `opencode-go/minimax-m2.7`
- **AND** the local router SHALL remain available as a managed custom provider
  pinned to alias `coding`
- **AND** the supported managed default `agent.reasoning_effort` SHALL be
  `medium`

#### Scenario: Full reset requires fresh Codex auth for the primary lane
- **WHEN** operators perform the full destructive reset of
  `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`
- **THEN** the reset SHALL remove persisted Codex auth from
  `/home/hermes/.hermes/auth.json`
- **AND** operators SHALL need to re-auth Codex before the normal primary lane
  is usable again
- **AND** the refreshed runtime contract SHALL not describe Codex as a
  Discord-only forced route
