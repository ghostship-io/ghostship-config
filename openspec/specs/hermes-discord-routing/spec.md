## MODIFIED Requirements

### Requirement: Hermes SHALL allow repo-managed free-response Discord channels
The self-hosted Hermes Discord gateway on `chill-penguin` SHALL allow a
configured single-agent channel list that responds without an `@mention`, with
`GHOSTSHIP_ROUTER_CHANNEL` as the only repo-owned forced-route channel.

#### Scenario: Managed Hermes free-response channels respond without mention
- **WHEN** Hermes receives a message in one of the configured managed
  free-response channels
- **THEN** Hermes SHALL treat that channel as a free-response channel
- **AND** the free-response channel list SHALL include `GHOSTSHIP_ROUTER_CHANNEL`
- **AND** the managed single-agent bot/auth scope SHALL still use the current
  supervisor identity values
- **AND** Hermes SHALL be allowed to respond without an explicit `@mention`
- **AND** the supported contract SHALL not require `GHOSTSHIP_CODEX_CHANNEL`

### Requirement: Hermes Discord routing changes SHALL be applied through host deployment
The self-hosted Hermes Discord routing policy on `chill-penguin` SHALL be
managed through repo-declared single-agent runtime configuration and loaded on
container startup.

#### Scenario: Updated routing policy is deployed
- **WHEN** the Hermes Discord routing configuration is changed in this repo and
  deployed to `chill-penguin`
- **THEN** the deployed Hermes container SHALL start with the updated generic
  Discord routing environment variables
- **AND** operators SHALL be able to verify that a Hermes restart or redeploy
  was performed to load the new policy
- **AND** the deployed contract SHALL not depend on `GHOSTSHIP_CODEX_CHANNEL`

## ADDED Requirements

### Requirement: Retired Codex Discord lane SHALL not remain a supported contract path
The self-hosted Hermes runtime on `chill-penguin` SHALL not treat a Codex-only
Discord lane as part of the supported downstream routing contract.

#### Scenario: Non-router free-response sessions use normal routing
- **WHEN** a Discord free-response session is not selected by
  `GHOSTSHIP_ROUTER_CHANNEL`
- **THEN** the session SHALL follow the normal runtime routing path for that
  session
- **AND** the session SHALL not require a repo-owned forced Codex route

#### Scenario: Stale retired env does not restore a supported pinned lane
- **WHEN** operators still have a stale `GHOSTSHIP_CODEX_CHANNEL` value from an
  older deployment
- **THEN** that stale value SHALL not be treated as part of the supported
  downstream contract
- **AND** the refreshed runtime contract SHALL describe only
  `GHOSTSHIP_ROUTER_CHANNEL` as a repo-owned forced Discord lane
