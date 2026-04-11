# hermes-discord-routing Specification

## Purpose
Define the repo-managed Discord mention policy, free-response channel
exceptions, and no-auto-thread behavior for Hermes on `chill-penguin`.

## Requirements
### Requirement: Hermes SHALL keep Discord mention-gating enabled by default
The self-hosted Hermes Discord gateway on `chill-penguin` SHALL require an
explicit `@mention` before responding in server channels unless a channel is
configured as a free-response exception.

#### Scenario: General channel remains mention-only
- **WHEN** Hermes receives a message in the configured Discord general channel
  without an `@mention`
- **THEN** Hermes SHALL not respond
- **AND** the general channel SHALL not be treated as a free-response channel

### Requirement: Hermes SHALL allow repo-managed free-response Discord channels
The self-hosted Hermes Discord gateway on `chill-penguin` SHALL allow
configured channel exceptions that respond without an `@mention`.

#### Scenario: Dedicated gateway channels respond without mention
- **WHEN** Hermes receives a message in the configured assistant, operations,
  or supervisor Discord channels
- **THEN** Hermes SHALL treat those channels as free-response channels
- **AND** Hermes SHALL be allowed to respond without an explicit `@mention`

### Requirement: Hermes SHALL reply in-channel without auto-created Discord threads
The self-hosted Hermes Discord gateway on `chill-penguin` SHALL disable the
upstream Discord auto-thread behavior and SHALL reply in the originating
channel instead of creating a new thread.

#### Scenario: Channel mention does not create a thread
- **WHEN** Hermes is `@mentioned` in a non-DM Discord server channel
- **THEN** Hermes SHALL not auto-create a Discord thread for that conversation
- **AND** Hermes SHALL direct its reply to the same channel context

### Requirement: Hermes Discord routing changes SHALL be applied through host deployment
The self-hosted Hermes Discord routing policy on `chill-penguin` SHALL be
managed through repo-declared runtime configuration and loaded on container
startup.

#### Scenario: Updated routing policy is deployed
- **WHEN** the Hermes Discord routing configuration is changed in this repo and
  deployed to `chill-penguin`
- **THEN** the deployed Hermes container SHALL start with the updated Discord
  routing environment variables
- **AND** operators SHALL be able to verify that a Hermes restart or redeploy
  was performed to load the new policy
