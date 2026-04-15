## ADDED Requirements

### Requirement: Hermes SHALL not seed default runtime skills from this repo
The self-hosted Hermes runtime on `chill-penguin` SHALL not copy any repo-managed default skill content into the runtime skill tree under `/home/hermes/.hermes/skills/`.

#### Scenario: Runtime preparation leaves the skill tree unseeded
- **WHEN** `podman-hermes` runtime preparation runs
- **THEN** it SHALL not copy `skill-creator`
- **AND** it SHALL not copy any other repo-managed skill directory into `/home/hermes/.hermes/skills/`

#### Scenario: Existing runtime skills remain operator-managed
- **WHEN** `/home/hermes/.hermes/skills/` already contains user-created or previously seeded content
- **THEN** the repo-managed runtime preparation SHALL leave that content unchanged
- **AND** it SHALL not treat any runtime skill directory as repo-owned default state
