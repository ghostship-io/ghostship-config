## Why

Codex currently prefers its built-in `skill-creator` over the repo-managed shared skill, so simply renaming the shared skill from `skills-creator` to `skill-creator` does not make the repo copy authoritative. The develop-host workflow now needs a durable override that survives Codex CLI updates and keeps the shared skill inventory aligned across agent surfaces.

## What Changes

- Rename the shared repo-managed `skills-creator` skill to `skill-creator` and keep it vendored exactly from `vercel-labs/agent-browser` tag `v0.9.3`.
- Update the curated shared skill inventory, Home Manager links, and Codex config wiring to reference `skill-creator` instead of `skills-creator`.
- Add a develop-host-managed Codex override step that replaces the built-in `~/.codex/skills/.system/skill-creator` directory with a symlink to the repo-managed shared `skill-creator` tree.
- Re-assert that Codex override after agent maintenance runs or other host-managed refresh paths so Codex upgrades do not silently restore the built-in copy.
- Update active documentation to describe the renamed shared skill and the Codex built-in override behavior, including any host activation or cleanup implications.

## Capabilities

### New Capabilities
- `codex-built-in-skill-overrides`: Defines how develop hosts make a repo-managed skill authoritative over a conflicting Codex built-in skill name.

### Modified Capabilities
- `shared-agent-skills`: Rename the vendored shared skill to `skill-creator`, update the curated inventory and wiring, and document the Codex override behavior.

## Impact

- Affects develop hosts, Home Manager shared skill links, Codex user-local runtime state under `~/.codex/skills/.system/`, and repo workflow documentation.
- Affects `home/config/skills/`, `home/profiles/develop.nix`, `modules/develop/codex-wrapper.nix`, and `modules/develop/agent-tooling.nix` or equivalent develop-host maintenance wiring.
- Requires host-managed activation or maintenance cleanup to remove any existing built-in Codex `skill-creator` directory before replacing it with the managed symlink.
