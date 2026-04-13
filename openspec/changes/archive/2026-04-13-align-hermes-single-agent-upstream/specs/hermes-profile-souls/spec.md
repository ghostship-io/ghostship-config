## REMOVED Requirements

### Requirement: Hermes SHALL provide managed persona seed content for each profile gateway
**Reason**: The single-agent runtime keeps one root `SOUL.md` seed instead of one file per managed profile gateway.
**Migration**: Replace the profile-local persona files with one root seed source that stages `/home/hermes/seeds/SOUL.md`.

### Requirement: Hermes SHALL seed missing profile SOUL files without overwriting existing ones
**Reason**: The runtime no longer owns profile-local `SOUL.md` seed paths.
**Migration**: Apply the same copy-if-missing behavior to the root single-agent `SOUL.md` seed path.

## ADDED Requirements

### Requirement: Hermes SHALL provide managed persona seed content for the single-agent runtime
The self-hosted Hermes runtime SHALL provide one repo-managed `SOUL.md` seed source for the single-agent Hermes runtime. That seed SHALL define the Crush Crawfish persona as the unified single-agent profile for personal assistance, operations, and software-delivery supervision.

#### Scenario: Root persona seed is defined
- **WHEN** the Hermes runtime assets are prepared from this repo
- **THEN** the repo SHALL define managed `SOUL.md` seed content under `modules/self-hosted/hermes-seeds/SOUL.md`
- **AND** that root `SOUL.md` SHALL use the provided Crush Crawfish single-agent prompt as the seed
- **AND** the runtime SHALL stage that file at `/home/hermes/seeds/SOUL.md`

### Requirement: Hermes SHALL seed the root SOUL file without overwriting existing seed content
The self-hosted Hermes runtime SHALL copy the managed root `SOUL.md` file into `/home/hermes/seeds/SOUL.md` only when that file is missing.

#### Scenario: Missing root SOUL file is seeded
- **WHEN** Hermes runtime preparation runs and `/home/hermes/seeds/SOUL.md` does not yet exist
- **THEN** the runtime preparation SHALL create the root seed directory if needed
- **AND** it SHALL copy the managed `SOUL.md` file into that path

#### Scenario: Existing root SOUL file is preserved
- **WHEN** Hermes runtime preparation runs and `/home/hermes/seeds/SOUL.md` already exists
- **THEN** the runtime preparation SHALL leave the existing file unchanged
- **AND** it SHALL not overwrite that file with the repo-managed version
