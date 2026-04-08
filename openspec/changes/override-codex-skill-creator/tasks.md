## 1. Rename the shared skill inventory

- [x] 1.1 Rename `home/config/skills/skills-creator/` to `home/config/skills/skill-creator/` and update all repo references, generated docs, and spec text that still use `skills-creator`
- [x] 1.2 Update `home/profiles/develop.nix` and `modules/develop/codex-wrapper.nix` so the curated shared skill links and Codex shared skill config reference `skill-creator`

## 2. Add the Codex built-in override

- [x] 2.1 Add develop-host-managed logic in `modules/develop/agent-tooling.nix` or the appropriate develop module to remove any existing `~/.codex/skills/.system/skill-creator` path and recreate it as a symlink to `~/.agents/skills/skill-creator`
- [x] 2.2 Ensure `ghostship-agent-maintenance` reasserts that symlink after Codex CLI install or upgrade so the override survives scheduled refreshes

## 3. Update docs and repo memory

- [x] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe the renamed shared `skill-creator` inventory entry and the managed Codex built-in override behavior
- [x] 3.2 Update any remaining active OpenSpec specs or generated repo docs that reference `skills-creator` so the published workflow matches the new runtime behavior

## 4. Verify the change

- [x] 4.1 Run `nix eval --raw '.#homeConfigurations.nixos@armored-armadillo.config.home.file.".agents/skills/skill-creator".source'` and `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.environment.etc."codex/config.toml".text'` to verify the shared skill link and Codex config reference `skill-creator`
- [x] 4.2 Run `nix eval --raw '.#packages.x86_64-linux.ghostship-agent-maintenance.outPath'` only if needed for inspection, then exercise the generated maintenance script path or an equivalent host build check to verify it recreates `~/.codex/skills/.system/skill-creator` as a symlink to `~/.agents/skills/skill-creator`
