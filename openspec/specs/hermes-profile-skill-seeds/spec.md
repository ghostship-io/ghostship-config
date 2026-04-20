## MODIFIED Requirements

### Requirement: Hermes SHALL not seed default runtime skills from this repo
The self-hosted Hermes runtime on `chill-penguin` SHALL not copy any
repo-managed default skill content into the runtime skill tree under
`/home/hermes/.hermes/skills/`.

#### Scenario: Runtime preparation leaves repo-managed defaults out of the skill tree
- **WHEN** `podman-hermes` runtime preparation runs
- **THEN** it SHALL not copy `skill-creator`
- **AND** it SHALL not copy any other repo-managed skill directory into
  `/home/hermes/.hermes/skills/`

#### Scenario: Existing runtime skills remain operator-managed
- **WHEN** `/home/hermes/.hermes/skills/` already contains user-created or
  previously seeded content
- **THEN** the repo-managed runtime preparation SHALL leave that content
  unchanged
- **AND** it SHALL not treat any runtime skill directory as repo-owned default
  state

## ADDED Requirements

### Requirement: Fresh resets SHALL rely on image-owned bundled default skill seeding
The full-reset Hermes rollout on `chill-penguin` SHALL rely on the current
upstream image to seed its bundled default skills into
`/home/hermes/.hermes/skills/`.

#### Scenario: Fresh reset boots with bundled default skills and no repo-seeded skill-creator
- **WHEN** Hermes boots after operators delete `/srv/apps/hermes/home`,
  `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`
- **THEN** the image SHALL be allowed to seed its bundled upstream default
  skills into `/home/hermes/.hermes/skills/`
- **AND** the repo-managed runtime preparation SHALL not restore `skill-creator`
- **AND** the fresh runtime SHALL not depend on any repo-seeded default skill
  inventory

#### Scenario: Later restarts preserve operator-owned skill state
- **WHEN** Hermes restarts after the fresh runtime has already created or
  modified skill content under `/home/hermes/.hermes/skills/`
- **THEN** repo-managed runtime preparation SHALL still avoid overwriting that
  operator-owned state
- **AND** the supported contract SHALL continue to distinguish image-owned
  bundled skill seeding from repo-managed default skill seeding
