## MODIFIED Requirements

### Requirement: Hermes SHALL allow repo-managed free-response Discord channels
The self-hosted Hermes Discord gateway on `chill-penguin` SHALL allow a configured single-agent channel list that responds without an `@mention`, including both the router-pinned and Codex-pinned Ghostship channels.

#### Scenario: Managed Hermes free-response channels respond without mention
- **WHEN** Hermes receives a message in one of the configured managed Hermes free-response channels
- **THEN** Hermes SHALL treat that channel as a free-response channel
- **AND** the free-response channel list SHALL include `1492841053642817606`, `1493462179725180959`, `1491229269127598281`, `1491229248856260799`, and `1491229299452412044`
- **AND** the managed single-agent bot/auth scope SHALL still use the current supervisor identity values
- **AND** Hermes SHALL be allowed to respond without an explicit `@mention`

#### Scenario: Pinned router and Codex channels remain free-response lanes
- **WHEN** repo-managed host wiring renders the Discord routing env for Hermes
- **THEN** the rendered `DISCORD_FREE_RESPONSE_CHANNELS` value SHALL include the values supplied through `GHOSTSHIP_ROUTER_CHANNEL` and `GHOSTSHIP_CODEX_CHANNEL`
- **AND** repo-managed wiring SHALL not allow either pinned channel to be omitted from the free-response list

### Requirement: Hermes Discord routing changes SHALL be applied through host deployment
The self-hosted Hermes Discord routing policy on `chill-penguin` SHALL be managed through repo-declared single-agent runtime configuration and loaded on container startup.

#### Scenario: Updated routing policy is deployed
- **WHEN** the Hermes Discord routing configuration is changed in this repo and deployed to `chill-penguin`
- **THEN** the deployed Hermes container SHALL start with the updated generic Discord routing environment variables
- **AND** operators SHALL be able to verify that a Hermes restart or redeploy was performed to load the new policy
