## ADDED Requirements

### Requirement: Hermes SHALL provide repo-managed shared skill seed content

The self-hosted Hermes runtime SHALL provide repo-managed shared skill seed
content under a source tree that maps to `/home/hermes/seeds/shared/skills/`
for the `chill-penguin` deployment.

#### Scenario: Managed shared skill seed content is defined for skill-creator

- **WHEN** the Hermes runtime assets are prepared from this repo
- **THEN** the repo SHALL define a managed shared skill seed source for
  `skill-creator`
- **AND** that source SHALL preserve the upstream `vercel-labs/agent-browser`
  `v0.9.3` `skills/skill-creator/` package layout before Hermes-specific
  adaptation
- **AND** that source SHALL include `SKILL.md`, `LICENSE.txt`, `references/`,
  and `scripts/`

### Requirement: Hermes SHALL seed missing shared skill directories without overwriting existing ones

The self-hosted Hermes runtime SHALL copy each managed shared skill directory
into `/home/hermes/seeds/shared/skills/<skill>/` only when that directory is
missing.

#### Scenario: Missing shared skill directory is seeded

- **WHEN** Hermes runtime preparation runs and
  `/home/hermes/seeds/shared/skills/skill-creator/` does not yet exist
- **THEN** the runtime preparation SHALL create the parent shared skill seed
  path if needed
- **AND** it SHALL copy the managed `skill-creator` seed directory into that
  path

#### Scenario: Existing shared skill directory is preserved

- **WHEN** Hermes runtime preparation runs and
  `/home/hermes/seeds/shared/skills/skill-creator/` already exists
- **THEN** the runtime preparation SHALL leave the existing directory unchanged
- **AND** it SHALL not overwrite that directory with the repo-managed version

### Requirement: Hermes-specific skill adaptation SHALL minimize markdown churn

The repo-managed Hermes `skill-creator` seed SHALL keep markdown changes narrow
and SHALL prefer Hermes-specific adaptation in metadata and scripts.

#### Scenario: Planned markdown edits are limited and reviewable

- **WHEN** the Hermes-specific `skill-creator` seed is prepared for
  implementation
- **THEN** the planned `SKILL.md` changes SHALL be limited to the reviewed
  frontmatter updates and minimal heading normalization needed for Hermes
- **AND** the adaptation SHALL preserve the rest of the upstream markdown body
  as much as practical
- **AND** Python scripts SHALL carry the primary Hermes-specific behavior
  changes for initialization and validation
