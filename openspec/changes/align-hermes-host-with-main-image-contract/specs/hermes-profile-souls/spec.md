## MODIFIED Requirements

### Requirement: Hermes SHALL provide managed persona seed content for the single-agent runtime
The self-hosted Hermes runtime SHALL provide one repo-managed `SOUL.md` default for the single-agent runtime and SHALL target the direct runtime path `/home/hermes/.hermes/SOUL.md` on `chill-penguin`.

#### Scenario: Root persona default is defined
- **WHEN** the Hermes runtime assets are prepared from this repo
- **THEN** the repo SHALL define managed `SOUL.md` content under `modules/self-hosted/hermes-seeds/SOUL.md`
- **AND** that `SOUL.md` SHALL use the provided Crush Crawfish single-agent prompt as the default
- **AND** the runtime SHALL target that file at `/home/hermes/.hermes/SOUL.md`

### Requirement: Hermes SHALL seed the root SOUL file without overwriting existing seed content
The self-hosted Hermes runtime SHALL copy the managed `SOUL.md` file into `/home/hermes/.hermes/SOUL.md` only when that file is missing.

#### Scenario: Missing root SOUL file is seeded directly into the runtime path
- **WHEN** Hermes runtime preparation runs and `/home/hermes/.hermes/SOUL.md` does not yet exist
- **THEN** the runtime preparation SHALL create the parent `.hermes/` path if needed
- **AND** it SHALL copy the managed `SOUL.md` file into `/home/hermes/.hermes/SOUL.md`

#### Scenario: Existing root SOUL file is preserved
- **WHEN** Hermes runtime preparation runs and `/home/hermes/.hermes/SOUL.md` already exists
- **THEN** the runtime preparation SHALL leave the existing file unchanged
- **AND** it SHALL not overwrite that file with the repo-managed version
