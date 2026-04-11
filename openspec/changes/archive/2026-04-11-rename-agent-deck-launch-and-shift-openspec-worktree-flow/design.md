## Context

This change touches two existing workflow contracts that are already wired into
multiple repo surfaces. The managed Agent Deck launcher is implemented as a
Home Manager helper in `home/profiles/develop.nix`, while the authoritative
Ghostship OpenSpec override wording is generated from
`modules/develop/agent-tooling.nix` and then copied into repo-visible Codex,
Gemini, and OpenCode surfaces after `openspec init` and `openspec update`.

Because both behaviors are already specified in active OpenSpec capabilities,
the design should update the existing contracts instead of introducing parallel
commands or duplicate override variants. The repo docs and AGENTS memory also
need to stay aligned, because they currently describe `agent-deck-launch` and
the older propose-on-`main` workflow.

## Goals / Non-Goals

**Goals:**
- Rename the managed Agent Deck project launcher from `agent-deck-launch` to
  `launch-agent`.
- Preserve the launcher's current behavior around current-directory targeting,
  group creation, default tool selection, and Agent Deck's supported `add -Q`
  plus `session start` flow.
- Move change-worktree creation or reuse into the Ghostship `propose`
  override so planning artifacts are created from the active change worktree.
- Keep `apply` centered on the existing change worktree and require clearer
  reporting of completed work, proposal updates, and issues found during apply.
- Require `archive` to report next issues or follow-up work after the archive
  flow finishes.
- Keep the wrapper-generated override text and the checked-in visible skill and
  command surfaces aligned.

**Non-Goals:**
- Change the underlying Agent Deck CLI behavior or introduce a second launcher
  with a different workflow.
- Rework unrelated agent launcher defaults or packaging outside the launcher
  rename.
- Change server-host deployment behavior.
- Implement a broader issue-tracking system beyond reporting issues and
  follow-up items in the generated flow summaries.

## Decisions

### Rename the existing managed launcher in place

The repo should rename the existing managed launcher command from
`agent-deck-launch` to `launch-agent` in place. The implementation should keep
the current shell-script behavior and only change the command name, usage text,
and repo-visible documentation/spec wording.

Alternatives considered:
- Add `launch-agent` as an alias while keeping `agent-deck-launch` as the
  primary command: rejected because it prolongs the old name in the active
  contract and documentation.
- Introduce a new launcher implementation in a different module: rejected
  because the current Home Manager helper already owns this behavior.

### Make the override generator the source of truth for the new workflow

The canonical wording for the revised propose/apply/archive flow should be
updated in `modules/develop/agent-tooling.nix`, then reflected in the checked-in
OpenSpec skill and command surfaces. This preserves the current source-of-truth
model and avoids repo-visible wording drifting away from the generated output.

Alternatives considered:
- Update only the checked-in skill files: rejected because `openspec update`
  would regenerate them from the old override source.
- Update only the wrapper and ignore the repo-visible surfaces: rejected
  because review and future exploration would keep seeing stale wording.

### Treat the worktree as the active change context from propose onward

The revised workflow should create or reuse the change worktree at the start of
propose, create planning artifacts from that worktree, and let apply continue
from the same worktree rather than creating a new one later. This aligns the
planning and implementation context and removes the current handoff from
proposal work on `main` to implementation work in a separate checkout.

Alternatives considered:
- Keep planning on `main` and only change the review-summary wording: rejected
  because it would not satisfy the requested workflow change.
- Create the worktree during propose but still require apply to recreate it:
  rejected because it duplicates state management and weakens the single-change-
  context model.

### Expand completion reporting instead of inventing new artifact types

The requested extra visibility should be handled as richer end-of-flow summary
requirements inside the propose/apply/archive overrides. `propose` should end
with a detailed overview of the planned change, `apply` should report completed
work plus proposal updates and issues found during apply, and `archive` should
end with a list of issues or follow-up work that should be considered next.

Alternatives considered:
- Add a new follow-up artifact to OpenSpec: rejected because the request is
  about agent output behavior during the existing flow, not about extending the
  schema.
- Keep issue tracking implicit during apply: rejected because the user
  explicitly wants those issues surfaced at the end of the flow.

## Risks / Trade-offs

- [Users may still reach for `agent-deck-launch` out of habit] -> Update active
  docs, changelog entries, AGENTS memory, and the launcher's help text together
  so the rename is clear after activation.
- [Moving planning into the worktree changes the long-standing expectation that
  proposal artifacts are created on `main`] -> Update the active spec and repo
  guidance explicitly so the new behavior is unambiguous.
- [Checked-in OpenSpec skill surfaces can drift from generated overrides again]
  -> Treat `modules/develop/agent-tooling.nix` as authoritative and refresh the
  visible surfaces in the same implementation change.
- [Issue and follow-up reporting may become noisy if phrased too rigidly] ->
  Keep the override wording focused on a detailed overview and issue list rather
  than imposing a heavy structured checklist.
