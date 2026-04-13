# shared-agent-skills Specification

## Purpose
Define the repo-managed shared skill inventory and how it differs from externally managed `skills.sh` installs.

## Requirements
### Requirement: Curated shared skill inventory
The repo SHALL expose exactly five shared repo-managed skills under `home/config/skills/`: `nix`, `python`, `ssh`, `wsl2`, and `skill-creator`.

#### Scenario: Removed shared skills are no longer present
- **WHEN** the shared skill tree is inspected after the change
- **THEN** `agent-browser`, `build123d`, and `dispatching-cli-subagents` SHALL not exist as shared repo-managed skills

#### Scenario: Retained shared skills remain available
- **WHEN** the shared skill tree is inspected after the change
- **THEN** `nix`, `python`, `ssh`, `wsl2`, and `skill-creator` SHALL exist as shared repo-managed skills

### Requirement: Rewritten local skills use a minimal modular format
The local shared skills `nix`, `python`, `ssh`, and `wsl2` SHALL use frontmatter containing only `name` and `description`, and SHALL keep detailed optional flows in one-level-deep modules instead of large SKILL bodies.

#### Scenario: Rewritten local skills remove extra metadata
- **WHEN** a rewritten local shared skill is inspected
- **THEN** its frontmatter SHALL not include `category`, `risk`, `source`, or `date_added`

#### Scenario: Optional detail is split out
- **WHEN** a rewritten local shared skill needs detailed workflow guidance
- **THEN** that detail SHALL live in directly linked `references/` or `scripts/` content no deeper than one level below the skill root

### Requirement: Vendored upstream skills preserve upstream package contents
The shared `skill-creator` skill SHALL be vendored exactly from `vercel-labs/agent-browser` tag `v0.9.3` `skill-creator` package and SHALL preserve the upstream package contents instead of being rewritten into local style.

#### Scenario: Vendored package keeps upstream layout
- **WHEN** `home/config/skills/skill-creator/` is inspected
- **THEN** it SHALL contain the upstream `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/` package contents from the pinned upstream source

#### Scenario: Vendored package is not rewritten
- **WHEN** `skill-creator` is compared to the pinned upstream package
- **THEN** its wording and bundled resources SHALL match the pinned upstream package rather than a locally rewritten variant

### Requirement: Shared skill wiring reflects the curated inventory
The Home Manager shared skill links and Codex shared skill wiring SHALL reference only the curated shared skill inventory.

#### Scenario: Develop profile links only curated shared skills
- **WHEN** the develop Home Manager profile is evaluated
- **THEN** it SHALL link only the curated shared repo-managed skills into `~/.agents/skills/`

#### Scenario: Codex shared skills omit removed entries
- **WHEN** the generated Codex config is inspected
- **THEN** its shared skill configuration SHALL not reference `build123d`

### Requirement: Externally managed skills stay outside the repo-owned skill tree
The repo SHALL keep external `skills.sh` installs distinct from the curated `home/config/skills/` inventory even when both surfaces land under `~/.agents/skills/` on a host.

#### Scenario: Managed external skill installs do not expand home/config/skills
- **WHEN** a configured external `skills.sh` repo such as `caveman` is installed on a host
- **THEN** it SHALL not require adding a matching directory under `home/config/skills/`

#### Scenario: Active docs distinguish repo-owned and external skill layers
- **WHEN** active documentation describes the repo’s agent skill surfaces
- **THEN** it SHALL distinguish the curated repo-owned `home/config/skills/` layer, the external `skills.sh` installs under `~/.agents/skills/`, and the repo-local OpenSpec-generated files under `.codex/`, `.gemini/`, and `.opencode/`
