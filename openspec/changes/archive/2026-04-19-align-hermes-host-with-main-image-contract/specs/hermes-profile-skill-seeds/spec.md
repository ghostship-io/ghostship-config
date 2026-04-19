## MODIFIED Requirements

### Requirement: Hermes SHALL provide repo-managed root skill seed content
The self-hosted Hermes runtime SHALL provide repo-managed `skill-creator` content for the single-agent runtime under the direct runtime path `/home/hermes/.hermes/skills/skill-creator/` for the `chill-penguin` deployment.

#### Scenario: Direct-runtime `skill-creator` content is defined
- **WHEN** the Hermes runtime assets are prepared from this repo
- **THEN** the repo SHALL define managed `skill-creator` content under `modules/self-hosted/hermes-seeds/skills/skill-creator/`
- **AND** the copied tree SHALL preserve the expected `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/` content
- **AND** the runtime SHALL target that tree at `/home/hermes/.hermes/skills/skill-creator/`

### Requirement: Hermes SHALL seed missing root skill directories without overwriting existing ones
The self-hosted Hermes runtime SHALL copy each managed direct-runtime skill directory into `/home/hermes/.hermes/skills/<skill>/` only when that directory is missing.

#### Scenario: Missing runtime skill directory is seeded directly into `.hermes`
- **WHEN** Hermes runtime preparation runs and `/home/hermes/.hermes/skills/skill-creator/` does not yet exist
- **THEN** the runtime preparation SHALL create the parent `.hermes/skills/` path if needed
- **AND** it SHALL copy the managed `skill-creator` directory into that path

#### Scenario: Existing runtime skill directory is preserved
- **WHEN** Hermes runtime preparation runs and `/home/hermes/.hermes/skills/skill-creator/` already exists
- **THEN** the runtime preparation SHALL leave the existing directory unchanged
- **AND** it SHALL not overwrite that directory with the repo-managed version

### Requirement: Hermes SHALL normalize copied root skill permissions for runtime ownership
The self-hosted Hermes runtime SHALL normalize copied direct-runtime skill content to writable runtime-owned permissions when it seeds a missing runtime skill directory.

#### Scenario: Seeded runtime skill tree becomes writable in the managed runtime
- **WHEN** Hermes runtime preparation copies `skill-creator` into `/home/hermes/.hermes/skills/skill-creator/` for the first time
- **THEN** the copied skill directory SHALL remain writable to the Hermes runtime user
- **AND** the copied files under that skill directory SHALL remain writable to the Hermes runtime user
- **AND** read-only permissions on the repo-managed source SHALL not make the managed destination immutable
