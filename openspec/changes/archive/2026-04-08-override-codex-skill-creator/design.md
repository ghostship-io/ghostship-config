## Context

The repo currently exposes a curated shared skill inventory through `home/config/skills/` and links that inventory into `~/.agents/skills/` on develop hosts. The vendored upstream authoring skill was renamed locally to `skills-creator` to avoid colliding with upstream or built-in `skill-creator` names, and Codex’s generated config advertises that renamed skill explicitly.

Recent investigation on this host showed that Codex also installs a built-in `skill-creator` under `~/.codex/skills/.system/skill-creator`, and that Codex prefers that built-in copy when both a repo-managed and a built-in `skill-creator` are present. That means a simple rename from `skills-creator` to `skill-creator` is insufficient: the repo skill would still lose inside Codex, while Gemini and the shared `~/.agents/skills` surface would see the renamed copy.

This change crosses multiple layers:

- the repo-managed shared skill inventory under `home/config/skills/`
- Home Manager links in `home/profiles/develop.nix`
- Codex-specific skill wiring and user-local runtime state
- develop-host maintenance that already refreshes agent CLIs and related runtime assets

Because Codex updates are host-managed and can recreate the built-in skill directory, the override must be declarative and durable rather than a one-off manual cleanup.

## Goals / Non-Goals

**Goals:**

- Make the repo-managed upstream-vendored `skill-creator` authoritative for Codex on develop hosts.
- Rename the shared skill inventory entry from `skills-creator` to `skill-creator`.
- Keep the repo copy pinned to the upstream `vercel-labs/agent-browser` `v0.9.3` package.
- Preserve the shared `~/.agents/skills` model for non-OpenSpec skills and avoid introducing a separate Codex-only repo skill source.
- Reapply the Codex override automatically after agent maintenance or other host-managed refresh paths.

**Non-Goals:**

- Changing Gemini or OpenCode built-in skill behavior beyond the shared rename.
- Rewriting the vendored `skill-creator` contents into local house style.
- Adding a generalized arbitrary built-in override framework for every Codex system skill.
- Changing Hermes seed behavior as part of this change.

## Decisions

### Rename the shared repo-managed skill to `skill-creator`

The repo-managed skill directory and frontmatter should use the upstream name `skill-creator`. This keeps the shared skill inventory consistent with upstream naming and matches the target name that Codex needs to override.

Alternative considered:

- Keep `skills-creator` for Codex and only use `skill-creator` elsewhere. Rejected because it preserves an unnecessary split name across agent surfaces and does not satisfy the user goal of making the shared skill override the built-in by name.

### Keep the repo as the source of truth and override Codex with a symlink

Develop hosts should replace `~/.codex/skills/.system/skill-creator` with a symlink to the repo-managed shared `skill-creator` directory. A symlink keeps the repo copy authoritative, avoids a duplicate Codex-specific copy, and makes future upstream refreshes visible to Codex without a second sync step.

Alternative considered:

- Copy the repo-managed skill into the Codex built-in path. Rejected because it creates two copies that can drift and makes verification harder.

### Reassert the symlink from host-managed maintenance

The existing `ghostship-agent-maintenance` flow already owns Codex CLI installation and periodic refresh, so it is the natural place to reassert the Codex `skill-creator` symlink after upgrades. If a Home Manager activation hook also performs cleanup, it should converge on the same final state, but maintenance must be sufficient on its own because Codex upgrades can happen after activation.

Alternative considered:

- Manual post-upgrade cleanup. Rejected because it is not durable.
- Home Manager activation only. Rejected because it does not cover later CLI upgrades by the maintenance timer.

### Scope the override narrowly to `skill-creator`

This change should only replace the built-in `skill-creator` path. The rest of Codex’s built-in `.system` skill tree should remain untouched.

Alternative considered:

- Replacing or disabling the whole `.system` skill tree. Rejected because it is broader than necessary and risks breaking unrelated built-in skills.

## Risks / Trade-offs

- `Codex update changes the built-in layout` → Keep the override scoped to the known `skill-creator` path and verify the path shape during implementation; if Codex moves the built-in location later, maintenance will need a small follow-up adjustment.
- `A pre-existing real directory blocks symlink creation` → Remove the managed target path first during activation or maintenance, then create the symlink atomically.
- `The shared skill path is unavailable when maintenance runs` → Point the symlink at the stable Home Manager-managed path under `~/.agents/skills/skill-creator` rather than a raw repo checkout path that may move.
- `Docs drift from runtime behavior` → Update README, CHANGELOG, and AGENTS as part of the same change and describe both the rename and the Codex built-in override explicitly.

## Migration Plan

1. Rename the shared skill directory and update all repo references from `skills-creator` to `skill-creator`.
2. Update Home Manager and Codex config generation to advertise `skill-creator`.
3. Add the develop-host maintenance or activation logic that removes any existing `~/.codex/skills/.system/skill-creator` directory and recreates it as a symlink to `~/.agents/skills/skill-creator`.
4. Verify that the generated shared skill inventory, Codex config, and maintenance logic converge on the new name and override behavior.
5. After deployment to a develop host, either wait for the timer or run `ghostship-agent-maintenance` to reassert the Codex symlink immediately.

Rollback is straightforward: remove the override logic, restore the shared skill name to `skills-creator`, and let Codex recreate or keep its built-in `skill-creator`.

## Open Questions

- None.
