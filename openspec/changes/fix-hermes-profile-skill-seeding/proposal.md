## Why

Hermes skill seeding is currently modeled around a shared runtime path at
`/home/hermes/seeds/shared/skills/`, but the active Hermes profile layout does
not have a usable global shared-skill folder. The repo is seeding `skill-creator`
into the wrong place, so Hermes cannot rely on that path as the authoritative
source of profile skills.

The requested fix is to copy the old shared skill seed content directly into
each profile's seed tree under `/home/hermes/seeds/profiles/<profile>/skills/<category>/`
and to retire the old shared-seed contract. Because stale shared-path artifacts
may already exist on the host, the change also needs an explicit manual cleanup
step as part of rollout.

## What Changes

- **BREAKING** Remove the active Hermes shared runtime skill-seed contract based
  on `/home/hermes/seeds/shared/skills/`.
- Copy the repo-managed `skill-creator` seed content into each managed Hermes
  profile seed tree under
  `modules/self-hosted/hermes-seeds/profiles/<profile>/skills/software-development/skill-creator/`.
- Seed `skill-creator` into each profile-local runtime path
  `/home/hermes/seeds/profiles/<profile>/skills/software-development/skill-creator/` only when that
  profile-owned seed directory is missing.
- Keep profile `SOUL.md` seeding separate from profile skill seeding while
  documenting that custom skills live under upstream category folders such as
  `software-development` inside the same profile-local seed root.
- Document the manual host cleanup required to remove stale shared skill seed
  artifacts after the updated config is applied.

## Capabilities

### New Capabilities
- `hermes-profile-skill-seeds`: Define repo-managed Hermes skill seed content
  copied into each profile-local `skills/<category>/` seed directory.

### Modified Capabilities
- `hermes-profile-souls`: Clarify that profile `SOUL.md` seed behavior now
  coexists with profile-local `skills/<category>/` seed directories instead of a separate
  shared skill seed root.

### Removed Capabilities
- `hermes-shared-skill-seeds`: Remove the obsolete shared runtime skill-seed
  contract rooted at `/home/hermes/seeds/shared/skills/`.

## Impact

- Affected code: `modules/self-hosted/hermes.nix`, repo-managed Hermes seed
  assets under `modules/self-hosted/hermes-seeds/`, and active OpenSpec/docs.
- Affected systems: `chill-penguin` Hermes runtime seed preparation and the
  persistent host-backed Hermes home tree.
- Affected scope: server-host config plus repo workflow/spec files; no change
  to the shared `home/config/skills/` inventory used outside Hermes.
- Activation/manual cleanup: after the updated config is applied, manually
  remove stale shared seed artifacts under
  `/srv/apps/hermes/home/seeds/shared/skills/`, including the old
  `skill-creator` tree and any now-empty parent directories that were used only
  for the retired shared-seed path.
