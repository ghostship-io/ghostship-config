## Why

Hermes already has a profile-seed model for runtime-owned state, but this repo
does not yet manage the per-profile `SOUL.md` files that define how the
`assistant`, `operations`, and `supervisor` personas should behave. We need a
repo-owned source of truth for those persona files so Hermes can seed them at
runtime without overwriting any profile state the container has already
materialized.

## What Changes

- Add repo-managed `SOUL.md` seed content for the Hermes `assistant`,
  `operations`, and `supervisor` profiles using the user-provided Toxic
  Seahorse, Volt Catfish, and Crush Crawfish persona definitions.
- Update the Hermes runtime preparation path so it creates the per-profile
  seed directories and copies each managed `SOUL.md` file into place only when
  that profile seed file does not already exist.
- Preserve the existing copy-once contract by never overwriting an existing
  profile `SOUL.md` file during subsequent starts or rebuilds.
- Update the Hermes documentation and change history to describe the new
  managed persona seed behavior and the operator-facing seed paths.

## Capabilities

### New Capabilities
- `hermes-profile-souls`: Define the managed per-profile `SOUL.md` seed content
  and copy-once runtime seeding behavior for Hermes profile gateways.

### Modified Capabilities

## Impact

- Affected code: `modules/self-hosted/hermes.nix` and any supporting repo files
  used to store the managed `SOUL.md` seed content.
- Affected docs: `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Affected system: the `chill-penguin` Hermes deployment and any future host
  that adopts the same Hermes runtime contract.
- Host activation impact: the new files are seeded during normal Hermes runtime
  preparation; existing profile `SOUL.md` files remain untouched.
