## MODIFIED Requirements

### Requirement: Hermes SHALL expose the bundled utility runtime env contract

The managed Hermes container on `chill-penguin` SHALL expose the non-secret
service URLs, selected secret-backed utility env, and profile source env
expected by the bundled `ghostship-*` utilities and the upstream
`ghostship-hermes` bootstrap through a container-wide env contract owned by the
repo-managed host wiring.

#### Scenario: Utility-facing service URLs are present on the Hermes container
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL set the utility-facing service URLs required by the shipped
  utilities, including `CHANGEDETECTION_URL`, `CHAPTARR_URL`,
  `PRICEBUDDY_URL`, `RSS_BRIDGE_URL`, and `SYNOLOGY_URL`
- **AND** `SYNOLOGY_URL` SHALL point at `http://192.168.200.106:5000/`

#### Scenario: Selected service-local secret sources remain the source of truth
- **WHEN** the Hermes runtime env is generated
- **THEN** repo-managed wiring SHALL read only the required Hermes-facing
  utility values from the existing service-local secret bundles and generated
  runtime env files
- **AND** Hermes SHALL not load whole unrelated service bundles only to reach a
  small subset of values
- **AND** the repo SHALL not require a second Hermes-only projection bundle
  that duplicates those same credentials

#### Scenario: URL-only utilities stay URL-only when auth is disabled
- **WHEN** the Ghostship stack keeps qBittorrent and NZBGet auth disabled for
  Hermes use
- **THEN** the Hermes runtime contract SHALL include `QBITTORRENT_URL` and
  `NZBGET_URL`
- **AND** it SHALL not require `QBITTORRENT_USER`, `QBITTORRENT_PASS`,
  `NZBGET_USER`, or `NZBGET_PASS` to be populated

#### Scenario: Repo-managed wiring does not write managed profile env files
- **WHEN** repo-managed Hermes wiring projects the runtime env contract for the
  container
- **THEN** it SHALL write only container-wide Hermes inputs such as runtime env
  files and container environment entries
- **AND** it SHALL not directly patch
  `~/.hermes/profiles/assistant/.env`,
  `~/.hermes/profiles/operations/.env`, or
  `~/.hermes/profiles/supervisor/.env`

#### Scenario: Shared unchanged env inputs remain available to all managed profiles
- **WHEN** the Hermes container starts with shared provider, browser-provider,
  and utility env set
- **THEN** upstream bootstrap SHALL be able to copy the supported unchanged
  inputs into every managed profile `.env`
- **AND** that unchanged pass-through set SHALL include
  `GOOGLE_AI_STUDIO_API_KEY`, `OPENROUTER_API_KEY`,
  `OPENROUTER_BASE_URL`, `OPENROUTER_HTTP_REFERER`,
  `OPENROUTER_TITLE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
  `OPENCODE_API_KEY`, `OPENCODE_GO_API_KEY`, `OPENCODE_BASE_URL`,
  `GITHUB_TOKEN`, `GH_TOKEN`, `HASS_URL`, `HASS_TOKEN`,
  `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`, `BROWSERBASE_API_KEY`,
  `BROWSERBASE_PROJECT_ID`, `BROWSER_USE_API_KEY`,
  `BROWSERBASE_PROXIES`, `BROWSERBASE_ADVANCED_STEALTH`,
  `BROWSERBASE_KEEP_ALIVE`, `BROWSERBASE_SESSION_TIMEOUT`,
  `BROWSER_INACTIVITY_TIMEOUT`, `CAMOFOX_URL`, `SEARXNG_URL`,
  `SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`,
  `PROWLARR_URL`, `PROWLARR_API_KEY`, `PLEX_URL`, `PLEX_TOKEN`,
  `ROMM_URL`, `ROMM_TOKEN`, `ROMM_USERNAME`, `ROMM_PASSWORD`,
  `NZBGET_URL`, `NZBGET_USER`, `NZBGET_PASS`, `QBITTORRENT_URL`,
  `QBITTORRENT_USER`, `QBITTORRENT_PASS`, `GRIMMORY_URL`,
  `GRIMMORY_TOKEN`, `GRIMMORY_USERNAME`, `GRIMMORY_PASSWORD`,
  `TAUTULLI_URL`, `TAUTULLI_API_KEY`, `BAZARR_URL`, `BAZARR_API_KEY`,
  `SYNOLOGY_URL`, `SYNOLOGY_USER`, `SYNOLOGY_PASS`,
  `SYNOLOGY_VERIFY_SSL`, `FLARESOLVERR_URL`, `PYLOAD_URL`,
  `PYLOAD_USER`, `PYLOAD_PASS`, `CLOAKBROWSER_URL`,
  `CLOAKBROWSER_TOKEN`, `PRICEBUDDY_URL`, `PRICEBUDDY_TOKEN`,
  `RSS_BRIDGE_URL`, `CHANGEDETECTION_URL`, `CHANGEDETECTION_API_KEY`,
  `CHAPTARR_URL`, `CHAPTARR_API_KEY`, `CHAPTARR_API_PATH`,
  `CHAPTARR_API_VERSION`, `N8N_URL`, `N8N_API_KEY`,
  `N8N_PUBLIC_API_ENDPOINT`, and `N8N_PUBLIC_API_VERSION`

#### Scenario: Container-only runtime env stays out of managed profile env files
- **WHEN** the Hermes container starts with runtime-only process env
- **THEN** upstream SHALL not write `HOME`, `HERMES_HOME`,
  `SSL_CERT_FILE`, `NIX_SSL_CERT_FILE`, `GHOSTSHIP_TERMINAL_CWD`,
  `GHOSTSHIP_HERMES_PROJECT_ROOT`, `GHOSTSHIP_HERMES_RUNTIME_FLAKE_REF`,
  `GHOSTSHIP_HERMES_PROFILES`, `GHOSTSHIP_HERMES_DEFAULT_PROFILE`,
  `GHOSTSHIP_HERMES_MANAGED_PROFILE`,
  `GHOSTSHIP_HERMES_SHARED_SKILLS_DIR`,
  `GHOSTSHIP_HERMES_PROFILE_SKILLS_ROOT`, `GHOSTSHIP_TOOLING_MODE`,
  `GHOSTSHIP_DASHBOARD_HOST`, any `GHOSTSHIP_ROUTER_*`,
  any `API_SERVER_*`, `GHOSTSHIP_TEST_CF_ACCESS_CLIENT_ID`, or
  `GHOSTSHIP_TEST_CF_ACCESS_CLIENT_SECRET` into managed profile `.env` files

### Requirement: Hermes SHALL derive managed profile env from shared and per-profile source inputs

The managed Hermes runtime SHALL write managed profile `.env` files from shared
container inputs, translated shared inputs, translated per-profile inputs, and
generated bootstrap defaults, while the repo contract SHALL provide only those
source inputs and never the final profile `.env` values directly.

#### Scenario: Shared translation is applied to every managed profile
- **WHEN** managed bootstrap or managed profile startup rewrites
  `~/.hermes/profiles/assistant/.env`,
  `~/.hermes/profiles/operations/.env`, and
  `~/.hermes/profiles/supervisor/.env`
- **THEN** each file SHALL contain `DISCORD_HOME_CHANNEL`
- **AND** `DISCORD_HOME_CHANNEL` SHALL be translated from the shared
  `DISCORD_GENERAL_CHANNEL_ID` input
- **AND** each file SHALL contain generated `TERMINAL_CWD=/workspace`
  and `WEBHOOK_ENABLED=true`

#### Scenario: Assistant profile receives assistant-specific translations
- **WHEN** upstream writes `assistant/.env`
- **THEN** it SHALL translate `DISCORD_ASSISTANT_BOT_TOKEN` to
  `DISCORD_BOT_TOKEN`
- **AND** it SHALL translate `DISCORD_ASSISTANT_ALLOWED_USERS` to
  `DISCORD_ALLOWED_USERS`
- **AND** it SHALL translate `DISCORD_ASSISTANT_CHANNEL_ID` to
  `DISCORD_FREE_RESPONSE_CHANNELS`
- **AND** it SHALL translate `WEBHOOK_ASSISTANT_SECRET` to
  `WEBHOOK_SECRET`
- **AND** it SHALL translate `BROWSER_ASSISTANT_CDP_URL` to
  `BROWSER_CDP_URL`
- **AND** it SHALL generate `WEBHOOK_PORT=8644`

#### Scenario: Operations profile receives operations-specific translations
- **WHEN** upstream writes `operations/.env`
- **THEN** it SHALL translate `DISCORD_OPERATIONS_BOT_TOKEN` to
  `DISCORD_BOT_TOKEN`
- **AND** it SHALL translate `DISCORD_OPERATIONS_ALLOWED_USERS` to
  `DISCORD_ALLOWED_USERS`
- **AND** it SHALL translate `DISCORD_OPERATIONS_CHANNEL_ID` to
  `DISCORD_FREE_RESPONSE_CHANNELS`
- **AND** it SHALL translate `WEBHOOK_OPERATIONS_SECRET` to
  `WEBHOOK_SECRET`
- **AND** it SHALL translate `BROWSER_OPERATIONS_CDP_URL` to
  `BROWSER_CDP_URL`
- **AND** it SHALL generate `WEBHOOK_PORT=8645`

#### Scenario: Supervisor profile receives supervisor-specific translations
- **WHEN** upstream writes `supervisor/.env`
- **THEN** it SHALL translate `DISCORD_SUPERVISOR_BOT_TOKEN` to
  `DISCORD_BOT_TOKEN`
- **AND** it SHALL translate `DISCORD_SUPERVISOR_ALLOWED_USERS` to
  `DISCORD_ALLOWED_USERS`
- **AND** it SHALL translate `DISCORD_SUPERVISOR_CHANNEL_ID` to
  `DISCORD_FREE_RESPONSE_CHANNELS`
- **AND** it SHALL translate `WEBHOOK_SUPERVISOR_SECRET` to
  `WEBHOOK_SECRET`
- **AND** it SHALL translate `BROWSER_SUPERVISOR_CDP_URL` to
  `BROWSER_CDP_URL`
- **AND** it SHALL generate `WEBHOOK_PORT=8646`

#### Scenario: OpenCode compatibility normalization remains available
- **WHEN** `OPENCODE_API_KEY` is unset and `OPENCODE_GO_API_KEY` is set
- **THEN** upstream SHALL also write `OPENCODE_API_KEY` with the
  `OPENCODE_GO_API_KEY` value into managed profile `.env`
