## MODIFIED Requirements

### Requirement: Hermes SHALL expose the bundled utility runtime env contract
The managed Hermes container on `chill-penguin` SHALL expose the non-secret service URLs, selected secret-backed utility env, and generic single-agent source env expected by the bundled `ghostship-*` utilities and upstream `ghostship-hermes` bootstrap through a container-wide contract owned by the repo-managed host wiring.

#### Scenario: Utility-facing service URLs are present on the Hermes container
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL set the utility-facing service URLs required by the shipped utilities, including `CHANGEDETECTION_URL`, `CHAPTARR_URL`, `PRICEBUDDY_URL`, `RSS_BRIDGE_URL`, and `SYNOLOGY_URL`
- **AND** `SYNOLOGY_URL` SHALL point at `http://192.168.200.106:5000/`

#### Scenario: Selected service-local secret sources remain the source of truth
- **WHEN** the Hermes runtime env is generated
- **THEN** repo-managed wiring SHALL read only the required Hermes-facing utility values from the existing service-local secret bundles and generated runtime env files
- **AND** Hermes SHALL not load whole unrelated service bundles only to reach a small subset of values
- **AND** the repo SHALL not require a second Hermes-only projection bundle that duplicates those same credentials

#### Scenario: URL-only utilities stay URL-only when auth is disabled
- **WHEN** the Ghostship stack keeps qBittorrent and NZBGet auth disabled for Hermes use
- **THEN** the Hermes runtime contract SHALL include `QBITTORRENT_URL` and `NZBGET_URL`
- **AND** it SHALL not require `QBITTORRENT_USER`, `QBITTORRENT_PASS`, `NZBGET_USER`, or `NZBGET_PASS` to be populated

#### Scenario: Repo-managed wiring does not write the managed root env file directly
- **WHEN** repo-managed Hermes wiring projects the runtime env contract for the container
- **THEN** it SHALL write only container-wide Hermes inputs such as runtime env files and container environment entries
- **AND** it SHALL not directly patch `/home/hermes/.hermes/.env`

#### Scenario: Shared unchanged env inputs remain available to the managed runtime
- **WHEN** the Hermes container starts with shared provider, browser-provider, and utility env set
- **THEN** upstream bootstrap SHALL be able to copy the supported unchanged inputs into the managed root `.env`
- **AND** that unchanged pass-through set SHALL include `GOOGLE_AI_STUDIO_API_KEY`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_HTTP_REFERER`, `OPENROUTER_TITLE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENCODE_API_KEY`, `OPENCODE_GO_API_KEY`, `OPENCODE_BASE_URL`, `GITHUB_TOKEN`, `GH_TOKEN`, `HASS_URL`, `HASS_TOKEN`, `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`, `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID`, `BROWSER_USE_API_KEY`, `BROWSERBASE_PROXIES`, `BROWSERBASE_ADVANCED_STEALTH`, `BROWSERBASE_KEEP_ALIVE`, `BROWSERBASE_SESSION_TIMEOUT`, `BROWSER_INACTIVITY_TIMEOUT`, `CAMOFOX_URL`, `SEARXNG_URL`, `SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`, `PROWLARR_URL`, `PROWLARR_API_KEY`, `PLEX_URL`, `PLEX_TOKEN`, `ROMM_URL`, `ROMM_TOKEN`, `ROMM_USERNAME`, `ROMM_PASSWORD`, `NZBGET_URL`, `NZBGET_USER`, `NZBGET_PASS`, `QBITTORRENT_URL`, `QBITTORRENT_USER`, `QBITTORRENT_PASS`, `GRIMMORY_URL`, `GRIMMORY_TOKEN`, `GRIMMORY_USERNAME`, `GRIMMORY_PASSWORD`, `TAUTULLI_URL`, `TAUTULLI_API_KEY`, `BAZARR_URL`, `BAZARR_API_KEY`, `SYNOLOGY_URL`, `SYNOLOGY_USER`, `SYNOLOGY_PASS`, `SYNOLOGY_VERIFY_SSL`, `FLARESOLVERR_URL`, `PYLOAD_URL`, `PYLOAD_USER`, `PYLOAD_PASS`, `CLOAKBROWSER_URL`, `CLOAKBROWSER_TOKEN`, `PRICEBUDDY_URL`, `PRICEBUDDY_TOKEN`, `RSS_BRIDGE_URL`, `CHANGEDETECTION_URL`, `CHANGEDETECTION_API_KEY`, `CHAPTARR_URL`, `CHAPTARR_API_KEY`, `N8N_URL`, and `N8N_API_KEY`

## REMOVED Requirements

### Requirement: Hermes SHALL derive managed profile env from shared and per-profile source inputs
**Reason**: Upstream now writes one managed root `.env` for the single-agent runtime instead of deriving separate profile-local env files from profile-scoped source inputs.
**Migration**: Supply only the generic single-agent source env names that upstream bootstrap expects and stop emitting `DISCORD_GENERAL_CHANNEL_ID`, profile-scoped `DISCORD_*`, profile-scoped `WEBHOOK_*`, and profile-scoped `BROWSER_*_CDP_URL` inputs.

## ADDED Requirements

### Requirement: Hermes SHALL use the generic single-agent Discord and webhook env contract
The self-hosted Hermes host wiring SHALL provide generic single-agent Discord and webhook source env to upstream bootstrap instead of profile-scoped translation inputs.

#### Scenario: Generic single-agent messaging env are present
- **WHEN** the Hermes container definition is evaluated after this change
- **THEN** it SHALL provide `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_FREE_RESPONSE_CHANNELS`, `DISCORD_HOME_CHANNEL`, and `WEBHOOK_SECRET` through the supported container env and env-file contract
- **AND** `DISCORD_BOT_TOKEN` and `DISCORD_ALLOWED_USERS` SHALL come from the current `supervisor` identity inputs
- **AND** `DISCORD_FREE_RESPONSE_CHANNELS` SHALL combine the current assistant, operations, and supervisor channel inputs
- **AND** `DISCORD_HOME_CHANNEL` SHALL use the current assistant channel input
- **AND** it SHALL not require profile-scoped translation inputs for Discord or webhook settings

### Requirement: Hermes SHALL omit repo-managed remote browser defaults
The self-hosted Hermes host wiring SHALL not provide a repo-managed browser CDP endpoint by default.

#### Scenario: Generated runtime env omits browser defaults
- **WHEN** the Hermes runtime env is generated after this change
- **THEN** it SHALL not include `BROWSER_CDP_URL`
- **AND** it SHALL not include any profile-scoped browser CDP source env names

### Requirement: Hermes SHALL preserve the upstream managed root env defaults and exclusions
The self-hosted Hermes host wiring SHALL preserve the upstream generated root `.env` defaults and exclusion rules while using the generic single-agent contract.

#### Scenario: Generated bootstrap defaults remain present
- **WHEN** upstream bootstrap rewrites `/home/hermes/.hermes/.env` from the host-provided container env after this change
- **THEN** the managed root `.env` SHALL contain `TERMINAL_CWD=/workspace`
- **AND** the managed root `.env` SHALL contain `WEBHOOK_ENABLED=true`
- **AND** the managed root `.env` SHALL contain `WEBHOOK_PORT=8644`
- **AND** the generic `WEBHOOK_SECRET` SHALL reuse the current supervisor secret value under its renamed single-agent key
- **AND** the single-agent webhook contract SHALL not preserve the old supervisor-specific webhook port

#### Scenario: OpenCode compatibility normalization remains available
- **WHEN** `OPENCODE_API_KEY` is unset and `OPENCODE_GO_API_KEY` is set during bootstrap
- **THEN** upstream SHALL also write `OPENCODE_API_KEY` with the `OPENCODE_GO_API_KEY` value into the managed root `.env`

#### Scenario: Fixed selectors and router internals stay outside the managed root env
- **WHEN** upstream bootstrap rewrites `/home/hermes/.hermes/.env` after this change
- **THEN** the managed root `.env` SHALL not contain `CHAPTARR_API_PATH`, `CHAPTARR_API_VERSION`, `N8N_PUBLIC_API_ENDPOINT`, or `N8N_PUBLIC_API_VERSION`
- **AND** the managed root `.env` SHALL not contain `GHOSTSHIP_ROUTER_API_KEY`, `API_SERVER_HOST`, `API_SERVER_PORT`, or `API_SERVER_KEY`
