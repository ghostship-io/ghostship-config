## MODIFIED Requirements

### Requirement: Hermes SHALL seed missing profile SOUL files without overwriting existing ones
The self-hosted Hermes runtime SHALL copy each managed profile `SOUL.md` file
into `/home/hermes/seeds/profiles/<profile>/SOUL.md` only when that file is
missing, and SHALL keep that profile seed behavior aligned with profile-local
skill seed behavior under `/home/hermes/seeds/profiles/<profile>/skills/`.

#### Scenario: Missing profile SOUL files are seeded
- **WHEN** Hermes runtime preparation runs and a profile `SOUL.md` file does
  not yet exist under `/home/hermes/seeds/profiles/<profile>/`
- **THEN** the runtime preparation SHALL create the profile seed directory if
  needed
- **AND** it SHALL copy the managed `SOUL.md` file into that path

#### Scenario: Existing profile SOUL files are preserved
- **WHEN** Hermes runtime preparation runs and a profile `SOUL.md` file already
  exists under `/home/hermes/seeds/profiles/<profile>/`
- **THEN** the runtime preparation SHALL leave the existing file unchanged
- **AND** it SHALL not overwrite that file with the repo-managed version

#### Scenario: Existing profile SOUL files are preserved alongside profile-local skill seeds
- **WHEN** Hermes runtime preparation runs and a profile `SOUL.md` file already
  exists under `/home/hermes/seeds/profiles/<profile>/`
- **THEN** the runtime preparation SHALL leave the existing file unchanged
- **AND** it SHALL not overwrite that file with the repo-managed version
- **AND** profile-local skill seed preparation under
  `/home/hermes/seeds/profiles/<profile>/skills/` SHALL remain a separate
  copy-once path
