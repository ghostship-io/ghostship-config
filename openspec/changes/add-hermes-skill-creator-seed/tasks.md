## 1. Hermes Seed Source

- [x] 1.1 Add a new repo-managed Hermes shared skill seed source under `modules/self-hosted/hermes-seeds/shared/skills/skill-creator/`.
- [x] 1.2 Copy the upstream `vercel-labs/agent-browser` `v0.9.3` `skills/skill-creator/` package into that Hermes seed source, preserving `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/` as the initial baseline.
- [x] 1.3 Apply the reviewed Hermes-specific adaptation to the Hermes seed copy, keeping `SKILL.md` edits limited to the planned frontmatter and heading changes and pushing the primary behavior changes into the Python scripts.

## 2. Runtime Seeding

- [x] 2.1 Update `modules/self-hosted/hermes.nix` so Hermes runtime preparation creates the shared seed path rooted at `/home/hermes/seeds/shared/skills/`.
- [x] 2.2 Seed `/home/hermes/seeds/shared/skills/skill-creator/` only when that runtime-owned directory is missing, preserving existing runtime state on later starts.
- [x] 2.3 Verify the generated runtime-preparation logic keeps shared skill seeding separate from the existing profile `SOUL.md` seed flow.

## 3. Verification and Docs

- [x] 3.1 Verify the repo-managed Hermes seed tree contains the expected upstream package files plus the reviewed Hermes-specific adjustments.
- [x] 3.2 Verify the relevant Nix configuration evaluates cleanly for the Hermes host path changes, including a concrete `nix eval` or build check for the affected host configuration.
- [x] 3.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` if implementation changes the documented Hermes seed contract or operating guidance.
