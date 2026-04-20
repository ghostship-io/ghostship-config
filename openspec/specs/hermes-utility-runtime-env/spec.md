## MODIFIED Requirements

### Requirement: Hermes SHALL expose the bundled utility runtime env contract
The managed Hermes container on `chill-penguin` SHALL expose the non-secret
service URLs, selected secret-backed utility env, and generic single-agent
source env expected by the bundled `ghostship-*` utilities through a
container-wide contract owned by the repo-managed host wiring.

#### Scenario: Utility-facing service URLs are present on the Hermes container
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL set the utility-facing service URLs required by the shipped
  utilities, including `CHANGEDETECTION_URL`, `CHAPTARR_URL`, `PRICEBUDDY_URL`,
  `RSS_BRIDGE_URL`, and `SYNOLOGY_URL`
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

#### Scenario: Shared unchanged env inputs remain available to the managed runtime
- **WHEN** the Hermes container starts with shared provider, browser-provider,
  and utility env set
- **THEN** the supported unchanged pass-through set SHALL include
  `GOOGLE_AI_STUDIO_API_KEY`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`,
  `OPENROUTER_HTTP_REFERER`, `OPENROUTER_TITLE`, `OPENAI_API_KEY`,
  `OPENAI_BASE_URL`, `OPENCODE_API_KEY`, `OPENCODE_GO_API_KEY`,
  `OPENCODE_BASE_URL`, `GITHUB_TOKEN`, `GH_TOKEN`, `HASS_URL`, `HASS_TOKEN`,
  `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`, `BROWSERBASE_API_KEY`,
  `BROWSERBASE_PROJECT_ID`, `BROWSER_USE_API_KEY`, `BROWSERBASE_PROXIES`,
  `BROWSERBASE_ADVANCED_STEALTH`, `BROWSERBASE_KEEP_ALIVE`,
  `BROWSERBASE_SESSION_TIMEOUT`, `BROWSER_INACTIVITY_TIMEOUT`, `SEARXNG_URL`,
  `SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`,
  `PROWLARR_URL`, `PROWLARR_API_KEY`, `PLEX_URL`, `PLEX_TOKEN`, `ROMM_URL`,
  `ROMM_TOKEN`, `ROMM_USERNAME`, `ROMM_PASSWORD`, `NZBGET_URL`,
  `QBITTORRENT_URL`, `GRIMMORY_URL`, `GRIMMORY_TOKEN`, `GRIMMORY_USERNAME`,
  `GRIMMORY_PASSWORD`, `TAUTULLI_URL`, `TAUTULLI_API_KEY`, `BAZARR_URL`,
  `BAZARR_API_KEY`, `SYNOLOGY_URL`, `SYNOLOGY_USER`, `SYNOLOGY_PASS`,
  `SYNOLOGY_VERIFY_SSL`, `FLARESOLVERR_URL`, `PYLOAD_URL`, `PYLOAD_API_KEY`,
  `PRICEBUDDY_URL`, `PRICEBUDDY_TOKEN`, `RSS_BRIDGE_URL`, `CHANGEDETECTION_URL`,
  `CHANGEDETECTION_API_KEY`, `CHAPTARR_URL`, `CHAPTARR_API_KEY`,
  `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, `BOOKSTACK_TOKEN_SECRET`, `N8N_URL`,
  and `N8N_API_KEY`

## REMOVED Requirements

### Requirement: Hermes SHALL derive managed profile env from shared and per-profile source inputs
**Reason**: Upstream now writes one managed root `.env` for the single-agent
runtime instead of deriving separate profile-local env files from
profile-scoped source inputs.
**Migration**: Supply only the generic single-agent source env names that
upstream bootstrap expects and stop emitting `DISCORD_GENERAL_CHANNEL_ID`,
profile-scoped `DISCORD_*`, profile-scoped `WEBHOOK_*`, and profile-scoped
`BROWSER_*_CDP_URL` inputs.

### Requirement: Hermes SHALL preserve the upstream managed root env defaults and exclusions
**Reason**: The current upstream workstation image no longer treats a
repo-regenerated `/home/hermes/.hermes/.env` as the host-owned projection
target for runtime defaults.
**Migration**: Treat the operator-facing runtime env as container runtime env
or an intentionally operator-managed persisted `.hermes/.env`, and stop
describing generated root `.env` defaults such as `TERMINAL_CWD` or
`WEBHOOK_PORT` as part of the host-owned contract.

## ADDED Requirements

### Requirement: Hermes SHALL treat fixed workstation env as image-owned internals
The managed Hermes container on `chill-penguin` SHALL treat the fixed
workstation layout, XDG, tool-root, browser, ttyd, and internal topology env as
image-owned internals rather than supported downstream operator inputs.

#### Scenario: Host wiring omits image-owned fixed env
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** repo-managed host wiring SHALL not set or document image-owned fixed
  env such as `HOME`, `HERMES_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`,
  `XDG_DATA_HOME`, `NPM_CONFIG_PREFIX`, `CARGO_HOME`, `RUSTUP_HOME`,
  `GHOSTSHIP_WORKSPACE_ROOT`, `GHOSTSHIP_WEB_PORT`,
  `GHOSTSHIP_DASHBOARD_HOST`, `GHOSTSHIP_DASHBOARD_PORT`,
  `GHOSTSHIP_ROUTER_HOST`, `GHOSTSHIP_ROUTER_PORT`, `GHOSTSHIP_ROUTER_URL`,
  `GHOSTSHIP_NIX_DEFAULT_PROFILE`, `GHOSTSHIP_TTYD_SOCKET`,
  `GHOSTSHIP_TTYD_BASE_PATH`, `GHOSTSHIP_TERMINAL_CWD`,
  `PLAYWRIGHT_BROWSERS_PATH`, or `AGENT_BROWSER_PROFILE`
- **AND** operators SHALL treat those values as unsupported downstream
  overrides

### Requirement: Hermes SHALL use runtime env or operator-owned `.hermes/.env` as downstream inputs
The managed Hermes runtime on `chill-penguin` SHALL use the supported
downstream operator env contract through container runtime env or an
intentionally operator-managed persisted `/home/hermes/.hermes/.env`.

#### Scenario: Repo-managed wiring does not rewrite the persisted root env file
- **WHEN** repo-managed Hermes wiring prepares the container runtime contract
- **THEN** it SHALL provide downstream-owned env only through container env and
  runtime env files
- **AND** it SHALL not directly patch `/home/hermes/.hermes/.env`
- **AND** it SHALL not assume the current image rewrites that file on behalf of
  the host

#### Scenario: Supported downstream env excludes the retired Codex lane key
- **WHEN** the Hermes runtime contract is documented for `chill-penguin`
- **THEN** the supported downstream Discord env surface SHALL include
  `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, and `GHOSTSHIP_ROUTER_CHANNEL`
- **AND** the supported downstream contract SHALL not require
  `GHOSTSHIP_CODEX_CHANNEL`

#### Scenario: Runtime env contract keeps Codex auth outside env
- **WHEN** operators prepare the fresh Hermes runtime after a full reset
- **THEN** the refreshed contract SHALL describe Codex auth as persisted state
  under `/home/hermes/.hermes/auth.json`
- **AND** the contract SHALL not replace that auth with a new downstream env
  key

### Requirement: Hermes SHALL use the generic single-agent Discord and webhook env contract
The self-hosted Hermes host wiring SHALL provide generic single-agent Discord
and webhook source env to upstream bootstrap instead of profile-scoped
translation inputs.

#### Scenario: Generic single-agent messaging env are present
- **WHEN** the Hermes container definition is evaluated after this change
- **THEN** it SHALL provide `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, `DISCORD_HOME_CHANNEL`, and
  `WEBHOOK_SECRET` through the supported container env and env-file contract
- **AND** `DISCORD_BOT_TOKEN` and `DISCORD_ALLOWED_USERS` SHALL come from the
  current `supervisor` identity inputs
- **AND** `DISCORD_FREE_RESPONSE_CHANNELS` SHALL combine the current managed
  free-response channels, with `GHOSTSHIP_ROUTER_CHANNEL` as the only
  repo-owned forced-route lane
- **AND** `DISCORD_HOME_CHANNEL` SHALL use the current assistant channel input
- **AND** it SHALL not require profile-scoped translation inputs for Discord or
  webhook settings

### Requirement: Hermes SHALL omit repo-managed remote browser defaults
The self-hosted Hermes host wiring SHALL not provide a repo-managed browser CDP
endpoint by default.

#### Scenario: Generated runtime env omits browser defaults
- **WHEN** the Hermes runtime env is generated after this change
- **THEN** it SHALL not include `BROWSER_CDP_URL`
- **AND** it SHALL not include any profile-scoped browser CDP source env names

### Requirement: Hermes SHALL treat native CloakBrowser launch as image-owned
The self-hosted Hermes host wiring SHALL not treat native CloakBrowser launch
details as part of the supported downstream operator env contract.

#### Scenario: Host wiring omits retired browser-service env
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL not set `CLOAKBROWSER_URL` or `CLOAKBROWSER_TOKEN`
- **AND** operators SHALL rely on the image-owned `google-chrome` plus
  `AGENT_BROWSER_PROFILE=/home/hermes/.local/state/cloakbrowser` path for the
  supported stock local browser workflow

### Requirement: Hermes SHALL project BookStack service access through the managed utility env contract
The managed Hermes container on `chill-penguin` SHALL expose the BookStack
service URL and token pair through the same repo-managed utility env contract
used for the rest of the bundled utilities.

#### Scenario: BookStack URL is present on the Hermes container
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL set `BOOKSTACK_URL`
- **AND** `BOOKSTACK_URL` SHALL point at `https://bookstack.ghostship.io`

#### Scenario: BookStack token pair is projected from the service-local secret bundle
- **WHEN** the Hermes runtime env is generated
- **THEN** repo-managed wiring SHALL read `BOOKSTACK_TOKEN_ID` and
  `BOOKSTACK_TOKEN_SECRET` from `bookstack-secrets`
- **AND** it SHALL write those values into the generated Hermes runtime env
  file
- **AND** it SHALL not require a second Hermes-only BookStack credential bundle
