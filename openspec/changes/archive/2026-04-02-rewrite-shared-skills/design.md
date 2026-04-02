## Context

This repo currently exposes a shared skill layer under `home/config/skills/`, linked into `~/.agents/skills/` on develop hosts. Those local skills were authored at different times and now vary in length, metadata shape, and how much generic guidance they include. At the same time, the user wants a canonical `skill-creator` skill from upstream available locally, and wants the rewritten local skills to conform to current skills.sh best practices without losing repo-specific operational constraints.

The current repo also has two distinct skill surfaces:
- shared repo-managed skills linked into `~/.agents/skills/`
- repo-local OpenSpec-generated skill/command files under `.codex/`, `.gemini/`, and `.opencode/`

This change only redesigns the shared repo-managed layer.

## Goals / Non-Goals

**Goals:**
- Reduce the shared local skill inventory to the skills that still provide repo-specific value.
- Rewrite the retained local skills to a concise, modular format that follows current skills.sh design guidance.
- Vendor `skill-creator` exactly from `vercel-labs/agent-browser` tag `v0.9.3`.
- Keep the linked shared skill inventory, Codex wiring, and active docs aligned with the final curated set.

**Non-Goals:**
- Changing the installed runtime tooling such as the `agent-browser` CLI wrapper.
- Rewriting the vendored `skill-creator` package into local house style.
- Changing the repo-local OpenSpec-generated skill/command files under `.codex/`, `.gemini/`, or `.opencode/`.

## Decisions

### Curate the shared skill inventory

The shared repo-managed inventory will be reduced to:
- `nix`
- `python`
- `ssh`
- `wsl2`
- `skill-creator`

`agent-browser`, `build123d`, and `dispatching-cli-subagents` will be removed entirely from the shared skill layer.

Why this approach:
- These three skills either duplicate tool help (`agent-browser`), can be covered by a more general retained skill plus normal reasoning (`build123d`), or encode workflow guidance that does not belong in a persistent shared skill (`dispatching-cli-subagents`).

Alternative considered:
- Keep all existing skills but trim them. Rejected because it preserves a noisy inventory and leaves low-value triggers active.

### Use a strict local skill format for rewritten skills

The retained local skills (`nix`, `python`, `ssh`, `wsl2`) will use:
- frontmatter with only `name` and `description`
- a short SKILL body with trigger guidance, core repo-specific workflow, and direct links to optional modules
- optional one-level-deep `references/` and `scripts/` only when they add repeated value

Why this approach:
- It matches the current skills.sh guidance on concise metadata, progressive disclosure, and avoiding context-heavy SKILL bodies.

Alternative considered:
- Preserve existing metadata fields and long-form content. Rejected because it keeps the current verbosity problem and drifts from the upstream guidance the user explicitly wants to follow.

### Vendor `skill-creator` as an upstream exception

`skill-creator` will be copied exactly from `https://github.com/vercel-labs/agent-browser/tree/v0.9.3/skills/skill-creator`, preserving upstream `SKILL.md`, `LICENSE.txt`, `references/`, and `scripts/`.

Why this approach:
- The user explicitly wants the upstream skill “exactly as it is written.”
- Vendoring the whole package preserves the intended package behavior, not just the top-level SKILL text.

Alternative considered:
- Rewriting `skill-creator` into local style. Rejected because it breaks the “exactly as written” requirement.

### Keep shared wiring and docs synchronized with the curated set

The skill links in Home Manager, Codex shared `skills.config`, and active shared-skill documentation will all be updated together in the same change.

Why this approach:
- Partial cleanup would leave removed skills advertised or wired after their directories are deleted.

Alternative considered:
- Clean content first and docs/wiring later. Rejected because it introduces drift immediately.

## Risks / Trade-offs

- [Removed skills were occasionally useful ad hoc] → Keep the underlying runtime tools installed where applicable, and rely on retained skills plus direct tool help for those workflows.
- [Vendored upstream skill can drift from future upstream changes] → Pin to `v0.9.3` explicitly and record the source URL in the change so future updates are intentional.
- [Aggressive trimming could remove repo-specific guidance that agents still need] → Preserve only the truly repo-specific operational constraints in the retained local SKILL bodies and move optional detail into references instead of deleting it outright.

## Migration Plan

1. Remove the deleted shared skill directories and their links.
2. Rewrite the retained local skills and keep or prune their existing references based on the new modular structure.
3. Vendor the upstream `skill-creator` package into `home/config/skills/skill-creator/`.
4. Update Codex shared skill wiring and active documentation.
5. Build both develop hosts to verify the new shared skill inventory evaluates cleanly.

Rollback is straightforward: revert the change to restore the previous shared skill tree and wiring.

## Open Questions

- None. The retained skill set, removed skill set, vendored upstream source, and structural rules are all fixed by the user’s stated requirements.
