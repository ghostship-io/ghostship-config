## REMOVED Requirements

### Requirement: Hermes SHALL preserve the upstream managed root env defaults and exclusions
The self-hosted Hermes host wiring SHALL preserve the upstream-generated root
`.env` defaults and exclusion rules while using the generic single-agent
contract.

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

### Requirement: Hermes SHALL treat native CloakBrowser launch as image-owned
The self-hosted Hermes host wiring SHALL not treat native CloakBrowser launch
details as part of the supported downstream operator env contract.

#### Scenario: Host wiring omits retired browser-service env
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL not set `CLOAKBROWSER_URL` or `CLOAKBROWSER_TOKEN`
- **AND** operators SHALL rely on the image-owned `google-chrome` plus
  `AGENT_BROWSER_PROFILE=/home/hermes/.local/state/cloakbrowser` path for the
  supported stock local browser workflow

### Requirement: Hermes SHALL support the image-managed Bitwarden CLI contract
The managed Hermes container on `chill-penguin` SHALL support the upstream
Password Manager CLI `bw` contract without restoring the retired Secrets
Manager-only `bws` contract as the normal path.

#### Scenario: Host wiring carries Bitwarden CLI appdata and credentials
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** repo-managed host wiring SHALL set
  `BITWARDENCLI_APPDATA_DIR=/home/hermes/.local/state/bitwarden-cli`
- **AND** `hermes-secrets` SHALL carry stubs for `BW_CLIENTID`,
  `BW_CLIENTSECRET`, and `BW_PASSWORD`
- **AND** operators SHALL fill those stubs before relying on `bw-unlock`
