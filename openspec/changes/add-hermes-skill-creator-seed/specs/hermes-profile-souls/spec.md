## MODIFIED Requirements

### Requirement: Hermes SHALL seed missing profile SOUL files without overwriting existing ones

The self-hosted Hermes runtime SHALL copy each managed profile `SOUL.md` file
into `/home/hermes/seeds/profiles/<profile>/SOUL.md` only when that file is
missing, and SHALL keep that profile seed behavior separate from shared skill
seed behavior under `/home/hermes/seeds/shared/skills/`.

#### Scenario: Existing profile SOUL files are preserved alongside shared skill seeds

- **WHEN** Hermes runtime preparation runs and a profile `SOUL.md` file already
  exists under `/home/hermes/seeds/profiles/<profile>/`
- **THEN** the runtime preparation SHALL leave the existing file unchanged
- **AND** it SHALL not overwrite that file with the repo-managed version
- **AND** shared skill seed preparation under `/home/hermes/seeds/shared/skills/`
  SHALL remain a separate copy-once path
