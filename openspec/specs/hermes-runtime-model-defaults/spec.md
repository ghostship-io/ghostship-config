## ADDED Requirements

### Requirement: Hermes SHALL use router primary with a forced Codex Discord lane
The self-hosted Hermes runtime on `chill-penguin` SHALL treat the current
upstream router-primary model contract and forced Codex Discord channel as the
supported default.

#### Scenario: Managed runtime uses router primary, Codex channel pin, and OpenCode Go fallback
- **WHEN** the refreshed Hermes runtime contract is applied on `chill-penguin`
- **THEN** the supported forced Discord Codex channel lane SHALL be
  `openai-codex/gpt-5.5`
- **AND** the supported managed fallback model lane SHALL be
  `opencode-go/minimax-m2.7`
- **AND** the local router SHALL remain available as a managed custom provider
  pinned to alias `agentic`
- **AND** the supported managed default `agent.reasoning_effort` SHALL be
  `medium`

#### Scenario: Full reset requires fresh Codex auth for the primary lane
- **WHEN** operators perform the full destructive reset of
  `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`
- **THEN** the reset SHALL remove persisted Codex auth from
  `/home/hermes/.hermes/auth.json`
- **AND** operators SHALL need to re-auth Codex before the forced Codex channel
  is usable again
- **AND** the refreshed runtime contract SHALL still allow the configured
  `GHOSTSHIP_CODEX_CHANNEL` to force Discord sessions onto Codex
