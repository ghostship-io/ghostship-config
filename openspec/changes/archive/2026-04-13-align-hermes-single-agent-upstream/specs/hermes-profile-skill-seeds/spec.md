## REMOVED Requirements

### Requirement: Hermes SHALL provide repo-managed profile-local skill seed content
**Reason**: The upstream single-agent runtime seeds one root skill tree instead of profile-local skill trees.
**Migration**: Move repo-managed Hermes skill seeds to the root source path and stage them under `/home/hermes/seeds/skills/<skill>/`.

### Requirement: Hermes SHALL seed missing profile-local skill directories without overwriting existing ones
**Reason**: The runtime no longer owns profile-local seed directories.
**Migration**: Apply the same copy-if-missing behavior to the root single-agent seed path under `/home/hermes/seeds/skills/`.

### Requirement: Hermes profile-local skills SHALL align to the upstream category layout
**Reason**: The upstream single-agent seed layout uses direct `/home/hermes/seeds/skills/<skill>/` directories instead of category/profile trees.
**Migration**: Place `skill-creator` directly under the root single-agent seed path rather than under `skills/<category>/`.

### Requirement: Hermes-specific skill adaptation SHALL remain consistent across profile-local copies
**Reason**: The runtime will keep only one root `skill-creator` copy instead of multiple profile-local copies.
**Migration**: Preserve the reviewed Hermes-specific `skill-creator` content in the one root seed source and runtime destination.

## ADDED Requirements

### Requirement: Hermes SHALL provide repo-managed root skill seed content
The self-hosted Hermes runtime SHALL provide repo-managed skill seed content for the single-agent runtime under a root source tree that maps to `/home/hermes/seeds/skills/<skill>/` for the `chill-penguin` deployment.

#### Scenario: Root `skill-creator` seed is defined
- **WHEN** the Hermes runtime assets are prepared from this repo
- **THEN** the repo SHALL define managed `skill-creator` seed content under `modules/self-hosted/hermes-seeds/skills/skill-creator/`
- **AND** the copied seed tree SHALL preserve the expected `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/` content

### Requirement: Hermes SHALL seed missing root skill directories without overwriting existing ones
The self-hosted Hermes runtime SHALL copy each managed root skill directory into `/home/hermes/seeds/skills/<skill>/` only when that directory is missing.

#### Scenario: Missing root skill directory is seeded
- **WHEN** Hermes runtime preparation runs and `/home/hermes/seeds/skills/skill-creator/` does not yet exist
- **THEN** the runtime preparation SHALL create the parent root `skills/` seed path if needed
- **AND** it SHALL copy the managed `skill-creator` seed directory into that path

#### Scenario: Existing root skill directory is preserved
- **WHEN** Hermes runtime preparation runs and `/home/hermes/seeds/skills/skill-creator/` already exists
- **THEN** the runtime preparation SHALL leave the existing directory unchanged
- **AND** it SHALL not overwrite that directory with the repo-managed version

### Requirement: Hermes SHALL normalize copied root skill permissions for runtime ownership
The self-hosted Hermes runtime SHALL normalize copied root skill seed content to writable runtime-owned permissions when it seeds a missing root skill directory.

#### Scenario: Seeded root skill tree becomes writable in the managed runtime
- **WHEN** Hermes runtime preparation copies `skill-creator` into the root runtime-managed skill destination for the first time
- **THEN** the copied skill directory SHALL remain writable to the Hermes runtime user
- **AND** the copied files under that skill directory SHALL remain writable to the Hermes runtime user
- **AND** read-only permissions on the repo-managed seed source SHALL not make the managed destination immutable
