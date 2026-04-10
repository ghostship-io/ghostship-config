# hermes-profile-skill-seeds Specification

## Purpose
Define repo-managed Hermes skill seed content and copy-once runtime seeding
behavior for profile-local skills under
`/home/hermes/seeds/profiles/<profile>/skills/<category>/`.

## Requirements
### Requirement: Hermes SHALL provide repo-managed profile-local skill seed content

The self-hosted Hermes runtime SHALL provide repo-managed skill seed content
under each managed profile source tree that maps to
`/home/hermes/seeds/profiles/<profile>/skills/<category>/` for the `chill-penguin`
deployment.

#### Scenario: Managed profile-local skill seeds are defined for each profile

- **WHEN** the Hermes runtime assets are prepared from this repo
- **THEN** the repo SHALL define managed `skill-creator` seed content for
  `assistant`, `operations`, and `supervisor` under their respective
  `modules/self-hosted/hermes-seeds/profiles/<profile>/skills/software-development/` paths
- **AND** each copied seed tree SHALL preserve the expected `SKILL.md`,
  `LICENSE.txt`, `references/`, and `scripts/` content

### Requirement: Hermes SHALL seed missing profile-local skill directories without overwriting existing ones

The self-hosted Hermes runtime SHALL copy each managed profile-local skill
directory into `/home/hermes/seeds/profiles/<profile>/skills/<category>/<skill>/` only
when that directory is missing.

#### Scenario: Missing profile-local skill directory is seeded

- **WHEN** Hermes runtime preparation runs and
  `/home/hermes/seeds/profiles/<profile>/skills/software-development/skill-creator/` does not yet
  exist
- **THEN** the runtime preparation SHALL create the parent profile-local
  `skills/<category>/` seed path if needed
- **AND** it SHALL copy the managed `skill-creator` seed directory into that
  path

#### Scenario: Existing profile-local skill directory is preserved

- **WHEN** Hermes runtime preparation runs and
  `/home/hermes/seeds/profiles/<profile>/skills/software-development/skill-creator/` already exists
- **THEN** the runtime preparation SHALL leave the existing directory unchanged
- **AND** it SHALL not overwrite that directory with the repo-managed version

### Requirement: Hermes profile-local skills SHALL align to the upstream category layout

The repo-managed Hermes profile-local skill tree SHALL place custom skills under
the upstream category directories `autonomous-ai-agents`, `creative`,
`data-science`, `devops`, `email`, `gaming`, `github`, `leisure`, `mcp`,
`media`, `mlops`, `note-taking`, `productivity`, `red-teaming`, `research`,
`smart-home`, `social-media`, and `software-development`.

#### Scenario: skill-creator is categorized under software-development

- **WHEN** the managed profile-local `skill-creator` trees are inspected
- **THEN** each profile copy SHALL live under
  `skills/software-development/skill-creator/` rather than directly under
  `skills/`

### Requirement: Hermes-specific skill adaptation SHALL remain consistent across profile-local copies

The repo-managed Hermes `skill-creator` seed copied into each profile-local
tree SHALL keep markdown changes narrow and SHALL preserve the same reviewed
Hermes-specific adaptation across all managed profiles.

#### Scenario: Profile-local copies stay aligned

- **WHEN** the managed profile-local `skill-creator` trees are inspected
- **THEN** each profile copy SHALL expose the same Hermes-reviewed
  `skill-creator` content rather than drifting by profile unless a later change
  explicitly introduces profile-specific divergence
