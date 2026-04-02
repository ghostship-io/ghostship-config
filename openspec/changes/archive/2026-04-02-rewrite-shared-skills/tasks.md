## 1. Inventory Cleanup

- [x] 1.1 Remove the shared `agent-browser`, `build123d`, and `dispatching-cli-subagents` skill directories from `home/config/skills/`
- [x] 1.2 Remove the deleted skill links from `home/profiles/develop.nix`
- [x] 1.3 Remove `build123d` from Codex shared `skills.config`

## 2. Retained Skill Rewrite

- [x] 2.1 Rewrite the shared `nix` skill to a minimal SKILL body and keep or reorganize detailed guidance under direct `references/`
- [x] 2.2 Rewrite the shared `python` skill to a minimal SKILL body and add direct optional modules only where they carry repeated value
- [x] 2.3 Rewrite the shared `ssh` skill to a minimal SKILL body, adding optional modules only if remote-edit or transfer flows still need them
- [x] 2.4 Rewrite the shared `wsl2` skill to a minimal SKILL body and keep or reorganize PowerShell, path, and troubleshooting guidance under direct `references/`

## 3. Vendored Upstream Skill

- [x] 3.1 Vendor `skill-creator` exactly from `vercel-labs/agent-browser` tag `v0.9.3` into `home/config/skills/skill-creator/`
- [x] 3.2 Preserve the upstream package layout, including `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/`
- [x] 3.3 Add the new shared `skill-creator` link to the develop profile

## 4. Documentation Alignment

- [x] 4.1 Update active shared-skill inventory docs to remove deleted skills and describe the curated shared skill set
- [x] 4.2 Update docs to distinguish shared repo-managed skills from repo-local OpenSpec-generated skill/command assets
- [x] 4.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` with the new shared skill inventory and the vendored upstream `skill-creator` source

## 5. Verification

- [x] 5.1 Verify the final shared skill tree contains only `nix`, `python`, `ssh`, `wsl2`, and `skill-creator`
- [x] 5.2 Run `nix build .#nixosConfigurations.launch-octopus.config.system.build.toplevel -L`
- [x] 5.3 Run `nix build .#nixosConfigurations.armored-armadillo.config.system.build.toplevel -L`
- [x] 5.4 Verify the generated develop-host skill wiring and active docs match the curated shared skill inventory
