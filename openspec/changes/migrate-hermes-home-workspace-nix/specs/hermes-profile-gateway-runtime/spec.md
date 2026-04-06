## ADDED Requirements

### Requirement: Hermes SHALL expose managed profile gateways as first-class runtime services
The self-hosted Hermes runtime SHALL treat the `assistant`, `operations`, and
`supervisor` profile gateways as first-class managed services for the
`chill-penguin` deployment.

#### Scenario: Managed profile gateways are present
- **WHEN** the Hermes runtime is configured for `chill-penguin`
- **THEN** it SHALL manage profile gateway services for `assistant`,
  `operations`, and `supervisor`
- **AND** those services SHALL be part of the supported runtime contract rather
  than incidental image internals

### Requirement: Hermes SHALL support runtime skill seeding from `/home/hermes/seeds`
The self-hosted Hermes runtime SHALL expose persistent seed paths under
`/home/hermes/seeds` for shared and per-profile skills and SHALL preserve the
image's copy-once seeding model for Hermes-owned runtime state.

#### Scenario: Shared skill seed path is present
- **WHEN** the Hermes home tree is prepared for `chill-penguin`
- **THEN** it SHALL expose a persistent shared skill seed path at
  `/home/hermes/seeds/shared/skills`

#### Scenario: Profile seed paths are present
- **WHEN** the Hermes home tree is prepared for `chill-penguin`
- **THEN** it SHALL expose persistent profile seed paths at
  `/home/hermes/seeds/profiles/assistant`,
  `/home/hermes/seeds/profiles/operations`, and
  `/home/hermes/seeds/profiles/supervisor`
- **AND** those profile seed paths SHALL support `skills/` content and optional
  `SOUL.md` content for each profile

#### Scenario: Seeded skills do not overwrite Hermes-owned runtime state
- **WHEN** Hermes copies shared or per-profile seeded skills into Hermes-owned
  state
- **THEN** it SHALL only copy missing skill directories or missing `SOUL.md`
  files
- **AND** it SHALL not overwrite existing Hermes-owned skills or existing
  profile `SOUL.md` files

### Requirement: Hermes SHALL propagate shared runtime env to bootstrap and managed profile gateways
The self-hosted Hermes runtime SHALL propagate the required shared runtime env
for model providers, Ghostship service integration, Discord profile gateways,
and workflow secrets into the Hermes bootstrap path and the managed profile
gateway services.

#### Scenario: Bootstrap receives model and workflow env
- **WHEN** the Hermes bootstrap path is generated
- **THEN** it SHALL receive `GOOGLE_AI_STUDIO_API_KEY`,
  `OPENCODE_GO_API_KEY`, `BWS_ACCESS_TOKEN`, and `BROWSER_CDP_URL`
- **AND** it SHALL receive the Hermes seed-directory settings required to
  resolve `/home/hermes/seeds/...`

#### Scenario: Managed profile gateways receive Ghostship service integration env
- **WHEN** the managed profile gateway services are generated
- **THEN** they SHALL receive the Ghostship service topology env required by
  the bundled `ghostship-*` utilities, including:
  `SEARXNG_URL`, `SONARR_URL`, `RADARR_URL`, `PROWLARR_URL`, `PLEX_URL`,
  `ROMM_URL`, `NZBGET_URL`, `QBITTORRENT_URL`, `GRIMMORY_URL`,
  `TAUTULLI_URL`, `BAZARR_URL`, `FLARESOLVERR_URL`, `PYLOAD_URL`,
  `CLOAKBROWSER_URL`, `SYNOLOGY_URL`, `SYNOLOGY_VERIFY_SSL`,
  `CHANGEDETECTION_URL`, `PRICEBUDDY_URL`, and `RSS_BRIDGE_URL`
- **AND** they SHALL receive the corresponding service auth secrets required by
  the enabled Ghostship integrations

#### Scenario: Managed profile gateways receive Discord env
- **WHEN** the managed profile gateway services are generated
- **THEN** they SHALL receive `DISCORD_GENERAL_CHANNEL_ID`
- **AND** `assistant` SHALL receive `DISCORD_ASSISTANT_BOT_TOKEN`,
  `DISCORD_ASSISTANT_ALLOWED_USERS`, and `DISCORD_ASSISTANT_CHANNEL_ID`
- **AND** `operations` SHALL receive `DISCORD_OPERATIONS_BOT_TOKEN`,
  `DISCORD_OPERATIONS_ALLOWED_USERS`, and `DISCORD_OPERATIONS_CHANNEL_ID`
- **AND** `supervisor` SHALL receive `DISCORD_SUPERVISOR_BOT_TOKEN`,
  `DISCORD_SUPERVISOR_ALLOWED_USERS`, and `DISCORD_SUPERVISOR_CHANNEL_ID`

### Requirement: Hermes SHALL propagate router provider env to the local router service
The self-hosted Hermes runtime SHALL propagate the router provider credentials
and compatibility settings required by the local Hermes router service.

#### Scenario: Router service receives provider env
- **WHEN** the local Hermes router service is generated
- **THEN** it SHALL receive `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
  `OPENROUTER_HTTP_REFERER`, `OPENROUTER_TITLE`, `OPENCODE_API_KEY`, and
  `OPENCODE_BASE_URL`
- **AND** it SHALL continue to receive the router host and compatibility
  listener settings required by the current image contract
