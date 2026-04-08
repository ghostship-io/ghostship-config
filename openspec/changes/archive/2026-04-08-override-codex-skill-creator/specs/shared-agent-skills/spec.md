## MODIFIED Requirements

### Requirement: Curated shared skill inventory
The repo SHALL expose exactly five shared repo-managed skills under `home/config/skills/`: `nix`, `python`, `ssh`, `wsl2`, and `skill-creator`.

#### Scenario: Removed shared skills are no longer present
- **WHEN** the shared skill tree is inspected after the change
- **THEN** `agent-browser`, `build123d`, and `dispatching-cli-subagents` SHALL not exist as shared repo-managed skills

#### Scenario: Retained shared skills remain available
- **WHEN** the shared skill tree is inspected after the change
- **THEN** `nix`, `python`, `ssh`, `wsl2`, and `skill-creator` SHALL exist as shared repo-managed skills

### Requirement: Vendored upstream skills preserve upstream package contents
The shared `skill-creator` skill SHALL be vendored exactly from `vercel-labs/agent-browser` tag `v0.9.3` `skill-creator` package and SHALL preserve the upstream package contents instead of being rewritten into local style.

#### Scenario: Vendored package keeps upstream layout
- **WHEN** `home/config/skills/skill-creator/` is inspected
- **THEN** it SHALL contain the upstream `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/` package contents from the pinned upstream source

#### Scenario: Vendored package is not rewritten
- **WHEN** `skill-creator` is compared to the pinned upstream package
- **THEN** its wording and bundled resources SHALL match the pinned upstream package rather than a locally rewritten variant

### Requirement: Shared skill wiring reflects the curated inventory
The Home Manager shared skill links and Codex shared skill wiring SHALL reference only the curated shared skill inventory, and the Codex shared skill entry SHALL use `skill-creator`.

#### Scenario: Develop profile links only curated shared skills
- **WHEN** the develop Home Manager profile is evaluated
- **THEN** it SHALL link only the curated shared repo-managed skills into `~/.agents/skills/`

#### Scenario: Codex shared skills omit removed entries
- **WHEN** the generated Codex config is inspected
- **THEN** its shared skill configuration SHALL not reference `build123d`

#### Scenario: Codex shared skills reference skill-creator
- **WHEN** the generated Codex config is inspected
- **THEN** its shared skill configuration SHALL reference `skill-creator` instead of `skills-creator`

### Requirement: Active documentation matches the final skill set
Active documentation for the shared skill inventory SHALL describe the curated shared skill set and SHALL distinguish it from repo-local OpenSpec-generated agent assets, and SHALL document that develop hosts override Codex's built-in `skill-creator` with the repo-managed shared skill.

#### Scenario: Removed skills are no longer advertised
- **WHEN** active shared-skill inventory documentation is inspected
- **THEN** it SHALL not advertise `agent-browser`, `build123d`, or `dispatching-cli-subagents` as shared repo-managed skills

#### Scenario: Shared and repo-local skill layers are distinguished
- **WHEN** active documentation describes the repo’s agent skill surfaces
- **THEN** it SHALL distinguish the shared `~/.agents/skills` layer from the repo-local OpenSpec-generated files under `.codex/`, `.gemini/`, and `.opencode/`

#### Scenario: Codex override behavior is documented
- **WHEN** active documentation describes the shared `skill-creator`
- **THEN** it SHALL state that develop hosts replace Codex's built-in `skill-creator` path with a managed symlink to the repo-managed shared skill
