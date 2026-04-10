## ADDED Requirements

### Requirement: Hermes SHALL expose the bundled utility runtime env contract
The managed Hermes container on `chill-penguin` SHALL expose the non-secret
service URLs and selected secret-backed utility env expected by the bundled
`ghostship-*` utilities that target the Ghostship self-hosted stack.

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

### Requirement: Hermes SHALL project per-profile CloakBrowser defaults into managed profile env
The managed Hermes runtime SHALL write a profile-specific `BROWSER_CDP_URL`
into each managed profile `.env` so `assistant`, `operations`, and
`supervisor` each default to their matching managed CloakBrowser profile.

#### Scenario: Managed profile env receives a matching profile-backed CDP URL
- **WHEN** managed bootstrap rewrites `~/.hermes/profiles/assistant/.env`,
  `~/.hermes/profiles/operations/.env`, and
  `~/.hermes/profiles/supervisor/.env`
- **THEN** each file SHALL contain a `BROWSER_CDP_URL` value
- **AND** that value SHALL point at
  `http://cloakbrowser:8080/api/profiles/<profile-id>/cdp`
- **AND** the `<profile-id>` SHALL be resolved from the matching managed
  CloakBrowser profile name instead of hard-coded in the repo

#### Scenario: Profile-specific source env does not collapse to one shared default
- **WHEN** the managed runtime prepares browser defaults for the three Hermes
  profiles
- **THEN** the source container env SHALL distinguish assistant, operations,
  and supervisor browser defaults
- **AND** managed bootstrap SHALL not stamp one shared `BROWSER_CDP_URL` into
  all three profile `.env` files

#### Scenario: Profile-backed CDP defaults do not require always-on browser sessions
- **WHEN** the managed Hermes runtime writes the profile-specific
  `BROWSER_CDP_URL` values
- **THEN** it SHALL not require the `assistant`, `operations`, or `supervisor`
  CloakBrowser profiles to be kept running continuously as part of this env
  contract alone

### Requirement: Hermes SHALL keep the router env scope minimal for this contract
The managed Hermes runtime SHALL expose only the current provider env required
for the shipped router/fallback path as part of this env contract change, and
SHALL not expand to the broader router tuning surface by default.

#### Scenario: Minimal provider env remains available
- **WHEN** the Hermes runtime env contract is generated for `chill-penguin`
- **THEN** it SHALL continue to expose the provider env needed for the current
  router and fallback path, including `OPENROUTER_API_KEY` and
  `OPENCODE_GO_API_KEY`
- **AND** it SHALL not require the broader `GHOSTSHIP_ROUTER_*` ranking and
  tuning variables to be configured for this change
