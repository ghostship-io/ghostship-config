## 1. Replace shared skill sources with profile-local copies

- [x] 1.1 Remove the repo-managed Hermes shared skill seed source under `modules/self-hosted/hermes-seeds/shared/skills/skill-creator/`.
- [x] 1.2 Add `skill-creator` under each managed profile seed tree at `modules/self-hosted/hermes-seeds/profiles/{assistant,operations,supervisor}/skills/software-development/skill-creator/` by copying the old shared skill content into each profile-local location.
- [x] 1.3 Verify the copied profile-local `skill-creator` trees still preserve the expected `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/` content.

## 2. Update Hermes runtime seeding

- [x] 2.1 Update `modules/self-hosted/hermes.nix` so Hermes runtime preparation creates `skills/<category>/` directories under each managed profile seed root.
- [x] 2.2 Seed `/home/hermes/seeds/profiles/<profile>/skills/software-development/skill-creator/` only when that profile-local directory is missing, without overwriting existing runtime-owned profile skill state.
- [x] 2.3 Remove the old shared runtime seed path creation and `skill-creator` seeding logic rooted at `/home/hermes/seeds/shared/skills/`.

## 3. Update active specs and docs

- [x] 3.1 Remove the active `hermes-shared-skill-seeds` requirement from `openspec/specs/` and replace it with an active profile-local skill-seeding requirement.
- [x] 3.2 Update `openspec/specs/hermes-profile-souls/spec.md` so it describes profile-local `skills/<category>/` content living alongside profile `SOUL.md` files.
- [x] 3.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` so they document the profile-local Hermes skill-seed contract and the retirement of the shared runtime path.

## 4. Verify and roll out

- [x] 4.1 Run concrete verification for the affected host config, such as `nix build .#nixosConfigurations.chill-penguin.config.system.build.toplevel -L`.
- [x] 4.2 Inspect the generated Hermes preStart logic or a narrower evaluation output to confirm it now prepares and seeds `profiles/<profile>/skills/software-development/skill-creator` instead of `shared/skills/skill-creator`.
- [x] 4.3 After applying the config on the host, manually remove stale shared seed artifacts under `/srv/apps/hermes/home/seeds/shared/skills/`, including the retired `skill-creator` tree, any now-empty parent directories that exist only for the old shared path, and the bad runtime copies under `/srv/apps/hermes/home/.hermes/skills/`.
- [x] 4.4 Run `openspec status --change fix-hermes-profile-skill-seeding` and confirm the proposal remains apply-ready.
