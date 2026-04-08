## Why

Hermes now supports shared runtime skill seeding under
`/home/hermes/seeds/shared/skills`, but this repo does not yet provide any
repo-managed shared Hermes skill sources. The user wants a Hermes-specific
shared `skill-creator` seed that starts as an exact copy of the upstream
`vercel-labs/agent-browser` `v0.9.3` package and is then adapted with minimal
markdown changes so Hermes can consume it cleanly.

## What Changes

- Add a new repo-managed Hermes shared skill seed source for `skill-creator`
  under `modules/self-hosted/hermes-seeds/shared/skills/`.
- Seed that Hermes-specific shared skill into
  `/home/hermes/seeds/shared/skills/skill-creator/` during Hermes runtime
  preparation without overwriting an existing runtime-owned copy.
- Copy the upstream `vercel-labs/agent-browser` `v0.9.3`
  `skills/skill-creator/` package into the Hermes seed source first, including
  `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/`.
- Adapt the Hermes seed copy for Hermes skill conventions, with the primary
  implementation work in Python scripts and only minimal `SKILL.md` edits.
- Document the exact planned `SKILL.md` edits up front for review before
  implementation proceeds.

## Capabilities

### New Capabilities
- `hermes-shared-skill-seeds`: Define repo-managed shared Hermes skill seed
  content and copy-once seeding behavior for shared skills under
  `/home/hermes/seeds/shared/skills/`.

### Modified Capabilities
- `hermes-profile-souls`: clarify that profile `SOUL.md` seed behavior coexists
  with separate shared skill seed behavior under `/home/hermes/seeds/shared/skills/`.

## Impact

- Affected code: `modules/self-hosted/hermes.nix` and new repo-managed Hermes
  seed assets under `modules/self-hosted/hermes-seeds/shared/skills/`.
- Affected systems: `chill-penguin` Hermes runtime seed preparation and the
  persistent host-backed Hermes home tree.
- Affected scope: server host NixOS config plus repo-managed Hermes seed files;
  no change to the shared `home/config/skills/` inventory used outside Hermes.
- Manual review implication: the planned `SKILL.md` edits for the Hermes copy
  will be listed explicitly in the design so they can be approved before any
  implementation work starts.
