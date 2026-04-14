## MODIFIED Requirements

### Requirement: Hermes SHALL expose the bundled utility runtime env contract
The managed Hermes container on `chill-penguin` SHALL expose the non-secret service URLs, selected secret-backed utility env, and downstream-facing runtime env expected by the bundled `ghostship-*` utilities and the current `ghostship-hermes` `main` image through the repo-managed container environment contract.

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

#### Scenario: Repo-managed wiring passes downstream env without rewriting the managed runtime env file
- **WHEN** repo-managed Hermes wiring projects the runtime env contract for the container
- **THEN** it SHALL pass supported downstream-facing env through the container environment and environment-file contract
- **AND** it SHALL not directly patch `/home/hermes/.hermes/.env`
- **AND** it SHALL not rely on the image to regenerate `/home/hermes/.hermes/.env` from host-provided values

#### Scenario: Image-owned fixed env stay out of host wiring
- **WHEN** the Hermes container environment is generated for the current image contract
- **THEN** repo-managed host wiring SHALL not set image-owned fixed vars such as `HOME`, `HERMES_HOME`, `GHOSTSHIP_WORKSPACE_ROOT`, `GHOSTSHIP_TERMINAL_CWD`, `GHOSTSHIP_WEB_PORT`, `GHOSTSHIP_DASHBOARD_HOST`, `GHOSTSHIP_DASHBOARD_PORT`, `GHOSTSHIP_ROUTER_HOST`, `GHOSTSHIP_ROUTER_PORT`, `GHOSTSHIP_ROUTER_URL`, `GHOSTSHIP_TTYD_SOCKET`, or `GHOSTSHIP_TTYD_BASE_PATH`
- **AND** repo-managed host wiring SHALL not emit legacy terminal vars such as `TTYD_PORT`, `TTYD_TITLE`, or `TTYD_SESSION_NAME`

### Requirement: Hermes SHALL use the generic single-agent Discord and webhook env contract
The self-hosted Hermes host wiring SHALL provide the generic Discord and webhook runtime env expected by the current `ghostship-hermes` `main` image instead of the older repo-specific translation inputs.

#### Scenario: Generic single-agent messaging env are present
- **WHEN** the Hermes container definition is evaluated after this change
- **THEN** it SHALL provide `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`, `DISCORD_FREE_RESPONSE_CHANNELS`, `GHOSTSHIP_ROUTER_CHANNEL`, `GHOSTSHIP_CODEX_CHANNEL`, and `WEBHOOK_SECRET` through the supported container env and env-file contract
- **AND** `DISCORD_BOT_TOKEN` and `DISCORD_ALLOWED_USERS` SHALL come from the current `supervisor` identity inputs
- **AND** `GHOSTSHIP_ROUTER_CHANNEL` SHALL be `1492841053642817606`
- **AND** `GHOSTSHIP_CODEX_CHANNEL` SHALL be `1493462179725180959`
- **AND** `DISCORD_FREE_RESPONSE_CHANNELS` SHALL include `1492841053642817606`, `1493462179725180959`, `1491229269127598281`, `1491229248856260799`, and `1491229299452412044`
- **AND** it SHALL not require profile-scoped translation inputs for Discord or webhook settings

## REMOVED Requirements

### Requirement: Hermes SHALL preserve the upstream managed root env defaults and exclusions
**Reason**: The current `ghostship-hermes` `main` image treats container runtime env as the primary downstream contract and leaves `/home/hermes/.hermes/.env` as optional downstream-owned state instead of a generated host-driven bootstrap output.
**Migration**: Stop relying on generated contents under `/home/hermes/.hermes/.env`, pass supported env directly through the container runtime contract, and keep image-owned fixed env out of repo-managed host wiring.
