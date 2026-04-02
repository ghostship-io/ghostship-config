## Why

The shared skills under `home/config/skills/` currently mix core repo-specific guidance with broad tutorials and optional detail, which makes them larger and less reusable than they need to be. This rewrite trims the shared skill set to the skills that still add repo-specific value, aligns their structure with current skills.sh guidance, and pins `skill-creator` to an exact upstream package so agents have the canonical authoring reference available locally.

## What Changes

- Remove the shared repo-managed skills for `agent-browser`, `build123d`, and `dispatching-cli-subagents`.
- Rewrite the shared `nix`, `python`, `ssh`, and `wsl2` skills to keep only trigger metadata, core repo-specific workflow guidance, and optional one-level-deep modules for detailed flows.
- Vendor the upstream `skill-creator` package exactly from `vercel-labs/agent-browser` tag `v0.9.3` into the shared skill tree.
- Update shared skill wiring and active docs so the linked `~/.agents/skills` inventory and documented skill list match the new curated set.

## Capabilities

### New Capabilities
- `shared-agent-skills`: Defines the curated shared skill inventory, the allowed structure for rewritten local skills, the vendoring rule for upstream `skill-creator`, and the required wiring/documentation updates.

### Modified Capabilities
- None.

## Impact

- Affects develop-host Home Manager skill linking and Codex shared skill wiring.
- Affects repo-only workflow files and documentation for the shared skill inventory.
- Introduces a pinned upstream vendored skill package under `home/config/skills/skill-creator/`.
