## ADDED Requirements

### Requirement: Develop hosts override Codex built-in skill-creator with the repo-managed skill
Develop hosts SHALL replace Codex's built-in `skill-creator` at `~/.codex/skills/.system/skill-creator` with a managed symlink to the repo-managed shared `skill-creator` so the repo copy is authoritative when Codex resolves that skill name.

#### Scenario: Existing built-in directory is replaced by a symlink
- **WHEN** the develop-host Codex override logic runs and `~/.codex/skills/.system/skill-creator` already exists as a real directory or file
- **THEN** it SHALL remove that existing path and recreate `~/.codex/skills/.system/skill-creator` as a symlink to the managed shared `skill-creator` path

#### Scenario: Repo-managed skill content becomes authoritative in Codex
- **WHEN** Codex resolves the `skill-creator` skill on a develop host after the override is applied
- **THEN** it SHALL read the repo-managed shared skill content through the overridden built-in path rather than the original bundled copy

### Requirement: Codex override persists across agent maintenance refreshes
Develop hosts SHALL reassert the managed `skill-creator` symlink after host-managed agent maintenance refreshes so Codex CLI upgrades do not silently restore the bundled built-in directory.

#### Scenario: Maintenance reasserts override after Codex updates
- **WHEN** `ghostship-agent-maintenance` refreshes the Codex CLI or otherwise runs its agent upkeep flow
- **THEN** the final on-disk state of `~/.codex/skills/.system/skill-creator` SHALL still be the managed symlink to the shared repo-managed `skill-creator`
