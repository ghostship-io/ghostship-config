## Context

The current Hermes module seeds repo-managed skill content under the shared
runtime path `/home/hermes/seeds/shared/skills/skill-creator/`, and the active
OpenSpec plus docs describe that as the supported contract. That path came from
an earlier assumption that Hermes would consume a global shared skill seed
directory in parallel with per-profile `SOUL.md` seeds.

The user has clarified that this assumption is wrong for the current Hermes
runtime: the old shared skill content should instead be copied into each
profile's local seed tree. In practice, that means the repo should stop
authoring or seeding a shared skill path and should duplicate the current
shared `skill-creator` seed into each managed profile's categorized
`skills/software-development/` directory.

This is a server-host and documentation change. It affects:

- `modules/self-hosted/hermes.nix`
- `modules/self-hosted/hermes-seeds/`
- `openspec/specs/hermes-shared-skill-seeds/spec.md`
- `openspec/specs/hermes-profile-souls/spec.md`
- `README.md`, `CHANGELOG.md`, and `AGENTS.md`

It also has a live-state implication: hosts that have already seeded the old
shared path need a manual cleanup step after rollout.

## Goals / Non-Goals

**Goals:**
- Retire the obsolete shared runtime skill-seed path
  `/home/hermes/seeds/shared/skills/`.
- Copy the old shared `skill-creator` seed content into each managed profile's
  categorized repo source tree and runtime seed tree.
- Keep profile-local seeding copy-once so runtime-owned profile state is not
  overwritten on later starts.
- Make the stale shared-path cleanup explicit in the rollout plan.
- Update active specs and docs so the repo contract matches the new profile-only
  model.

**Non-Goals:**
- Changing the shared develop-host skill inventory under `home/config/skills/`.
- Introducing a new runtime-global Hermes skill abstraction.
- Overwriting existing profile-local runtime skill directories once they exist.
- Automating deletion of runtime-owned host artifacts during activation.

## Decisions

### Decision: Replace the shared Hermes skill-seed contract with profile-local duplication

The repo should remove the dedicated shared Hermes skill-seed source tree and
instead copy the old shared `skill-creator` seed content into each managed
profile source tree under the upstream category structure:

- `modules/self-hosted/hermes-seeds/profiles/assistant/skills/software-development/skill-creator/`
- `modules/self-hosted/hermes-seeds/profiles/operations/skills/software-development/skill-creator/`
- `modules/self-hosted/hermes-seeds/profiles/supervisor/skills/software-development/skill-creator/`

At runtime, Hermes should seed those directories into:

- `/home/hermes/seeds/profiles/assistant/skills/software-development/skill-creator/`
- `/home/hermes/seeds/profiles/operations/skills/software-development/skill-creator/`
- `/home/hermes/seeds/profiles/supervisor/skills/software-development/skill-creator/`

Why:
- It matches the user's clarified runtime model.
- It keeps the seed location aligned with the profile that will consume it.
- It removes an extra runtime path that currently has no real consumer.

Alternatives considered:
- Keep a repo-level shared source and fan it out into profiles at runtime:
  rejected because the user explicitly wants the old shared skill copied into
  each profile now, not maintained as a separate live concept.
- Keep seeding the shared runtime path and rely on Hermes to fan out later:
  rejected because that is the broken model this change is replacing.

### Decision: Keep profile skill seeding copy-once per profile

Each profile-local `skills/<category>/<skill>/` directory should be seeded only when the
 target directory is missing under `/home/hermes/seeds/profiles/<profile>/`.

Why:
- It preserves the same operator-owned runtime behavior used elsewhere in the
  Hermes seed model.
- It avoids overwriting runtime-local edits after the initial seed.
- It keeps the implementation symmetric with existing `SOUL.md` copy-once
  behavior.

Alternatives considered:
- Force-copy repo updates into existing profile skill directories: rejected
  because it would unexpectedly overwrite runtime-owned profile state.

### Decision: Treat shared-path cleanup as a manual rollout step

The repo should remove the old shared seed path from declarative config, but
cleanup of already-materialized host artifacts under
`/srv/apps/hermes/home/seeds/shared/skills/` should stay manual and explicit.

Why:
- The host path is mutable runtime state, not just declarative config output.
- The user explicitly asked to include manual cleanup as part of the proposal.
- Manual cleanup keeps the change narrow and avoids accidental deletion of any
  operator-owned state beyond the retired shared-seed path.

Alternatives considered:
- Delete the old shared runtime path automatically during activation: rejected
  because activation should not aggressively remove mutable runtime state.

## Risks / Trade-offs

- [Duplicating the same seed tree into each profile increases repo footprint]
  -> Accept the duplication because it makes the runtime contract explicit and
  removes the broken shared indirection.
- [A host may still carry stale shared-path artifacts after rollout]
  -> Document the exact cleanup target under
  `/srv/apps/hermes/home/seeds/shared/skills/`.
- [Specs and docs could drift again if both old and new models remain described]
  -> Remove the shared-skill capability and update the remaining profile-facing
  artifacts in the same change.

## Migration Plan

1. Remove the old shared Hermes skill-seed source tree and replace it with
   per-profile copies of `skill-creator` under
   `modules/self-hosted/hermes-seeds/profiles/<profile>/skills/software-development/`.
2. Update `modules/self-hosted/hermes.nix` so Hermes runtime preparation creates
   each profile `skills/software-development/` seed directory and seeds
   `skill-creator` there only when missing.
3. Remove the declarative shared runtime seed path creation and old shared
   `skill-creator` seeding logic from the Hermes module.
4. Update the active OpenSpec requirements and docs to remove the shared-seed
   contract and describe the profile-local replacement.
5. Rebuild `chill-penguin` with:
   `nixos-rebuild build --flake .#chill-penguin -L`
6. Activate with:
   `./result/bin/switch-to-configuration switch`
7. Manually remove stale shared seed artifacts from the live host:
   - `/srv/apps/hermes/home/seeds/shared/skills/skill-creator`
   - any now-empty parent directories under
     `/srv/apps/hermes/home/seeds/shared/` that exist only for the retired
     shared skill path
8. Verify that each managed profile now has a profile-local seed tree at:
   - `/srv/apps/hermes/home/seeds/profiles/assistant/skills/software-development/skill-creator`
   - `/srv/apps/hermes/home/seeds/profiles/operations/skills/software-development/skill-creator`
   - `/srv/apps/hermes/home/seeds/profiles/supervisor/skills/software-development/skill-creator`

Rollback would restore the previous shared-seed source tree, revert the Hermes
module and docs/specs, rebuild the host, and if needed recreate the shared
runtime seed path from Git-managed sources.

## Open Questions

- None. The requested direction is explicit: the old shared skill content
  should now be copied into each profile's categorized `skills/<category>/` folder,
  and `skill-creator` belongs under `software-development`.
