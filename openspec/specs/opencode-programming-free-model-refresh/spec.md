# opencode-programming-free-model-refresh Specification

## Purpose
Define how the OpenCode launcher refreshes and caches OpenRouter programming free models at launch time.

## Requirements

### Requirement: OpenCode SHALL derive programming free models from OpenRouter's ranked frontend endpoint
The OpenCode launcher SHALL fetch the OpenRouter frontend models endpoint for the programming category and SHALL derive its configured OpenRouter model list from the free-priced models returned by that response.

#### Scenario: Launcher requests the ranked programming free endpoint
- **WHEN** the OpenCode launcher refreshes its model list
- **THEN** it SHALL request `https://openrouter.ai/api/frontend/models/find?categories=programming&fmt=cards&max_price=0&order=top-weekly`

#### Scenario: Launcher filters models by returned free pricing
- **WHEN** the frontend endpoint returns programming-category model data
- **THEN** the launcher SHALL only include models whose returned endpoint pricing indicates free prompt and completion cost in the generated OpenCode model map

### Requirement: OpenCode SHALL refresh the generated model config no more than once per day
The OpenCode launcher SHALL cache the generated programming free model config and SHALL refresh it at most once per day.

#### Scenario: Stale cache triggers refresh
- **WHEN** the generated model config is missing or older than the current daily refresh window
- **THEN** the launcher SHALL fetch the endpoint again and rewrite the generated config

#### Scenario: Fresh cache skips network refresh
- **WHEN** the generated model config was already refreshed during the current daily refresh window
- **THEN** the launcher SHALL reuse the cached generated config without issuing another endpoint request

### Requirement: OpenCode SHALL continue using the last good generated config when refresh fails
The OpenCode launcher SHALL treat model refresh as a warning-only preflight step and SHALL continue with the last good generated config if refresh fails after a successful prior refresh.

#### Scenario: Refresh failure reuses previous generated config
- **WHEN** endpoint fetch, response parsing, or generated config writing fails and a previous generated config exists
- **THEN** the launcher SHALL emit a warning and continue launching OpenCode with the previously generated config

#### Scenario: First refresh failure does not leave a partial config
- **WHEN** endpoint fetch, response parsing, or generated config writing fails before any valid generated config exists
- **THEN** the launcher SHALL not leave a partial generated config file behind
