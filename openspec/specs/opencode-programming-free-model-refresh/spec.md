# opencode-programming-free-model-refresh Specification

## Purpose
Define how the develop-host agent maintenance service refreshes OpenRouter programming free models for OpenCode.

## Requirements

### Requirement: Agent maintenance SHALL derive programming free models from OpenRouter's ranked frontend endpoint
The develop-host agent maintenance service SHALL fetch the OpenRouter frontend models endpoint for the programming category and SHALL derive OpenCode's configured OpenRouter model list from the free-priced models returned by that response.

#### Scenario: Maintenance requests the ranked programming free endpoint
- **WHEN** the agent maintenance service refreshes the OpenCode model list
- **THEN** it SHALL request `https://openrouter.ai/api/frontend/models/find?categories=programming&fmt=cards&max_price=0&order=top-weekly`

#### Scenario: Maintenance filters models by returned free pricing
- **WHEN** the frontend endpoint returns programming-category model data
- **THEN** the service SHALL only include models whose returned endpoint pricing indicates free prompt and completion cost in the generated OpenCode model map

### Requirement: Agent maintenance SHALL run on boot and every four hours with persistent catch-up
The develop-host agent maintenance timer SHALL trigger the OpenCode model refresh at boot and every four hours afterward, and SHALL use `Persistent = true` so missed runs fire after resume or downtime.

#### Scenario: Boot-triggered maintenance runs after startup
- **WHEN** the generated timer is inspected
- **THEN** it SHALL trigger the maintenance service on boot

#### Scenario: Periodic maintenance repeats every four hours
- **WHEN** the generated timer is inspected
- **THEN** it SHALL schedule the maintenance service every four hours

#### Scenario: Persistent timer catches up after WSL resume
- **WHEN** the host misses one or more scheduled maintenance runs while suspended or offline
- **THEN** the timer SHALL run the maintenance service after the host resumes because `Persistent` is enabled

### Requirement: Agent maintenance SHALL continue using the last good generated config when refresh fails
The develop-host agent maintenance service SHALL treat model refresh as a warning-only maintenance step and SHALL continue using the last good generated config if refresh fails after a successful prior refresh.

#### Scenario: Refresh failure reuses previous generated config
- **WHEN** endpoint fetch, response parsing, or generated config writing fails and a previous generated config exists
- **THEN** the service SHALL emit a warning and leave the previously generated config in place

#### Scenario: First refresh failure does not leave a partial config
- **WHEN** endpoint fetch, response parsing, or generated config writing fails before any valid generated config exists
- **THEN** the service SHALL not leave a partial generated config file behind
