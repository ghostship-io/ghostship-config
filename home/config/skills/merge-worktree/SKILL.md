---
name: merge-worktree
description: Finish a Codex Desktop or other git worktree and reconcile it back into local `main`, including detached HEAD worktrees. Use when Claude needs to review and commit outstanding work, best-effort update `README.md` / `CHANGELOG.md` / `VERSION`, merge local `main` into the finished worktree if needed, and fast-forward local `main` to the result while leaving worktree cleanup to Codex/Desktop.
---

# merge-worktree

Use this skill to finish a non-`main` worktree and fold it back into local
`main` for personal repositories.

## Core workflow

- Run `$HOME/.agents/skills/merge-worktree/scripts/finalize_worktree.sh inspect --target-branch main`
  from the active worktree first. The helper is bundled with this skill; do
  not look for a repo-local `scripts/finalize_worktree.sh`.
- Treat the `inspect` output as the canonical local preflight report for the
  merge-back flow. Do not do extra ad hoc git inspection unless `inspect`
  itself looks wrong.
- Use `inspect` to review:
  - `incoming_commit=` lines for what is not yet on local `main`
  - `source_dirty_path=` / `source_conflict_path=` lines for source-worktree
    cleanup
  - `main_dirty_path=` / `target_conflict_path=` / `overlap_path=` lines for
    target-worktree risk
  - `needs_main_merge=`, `can_fast_forward_main=`, and `can_finish_now=` for
    the finish decision
- If `can_finish_now=no`, fix the reported blockers and rerun `inspect` until
  it reports `can_finish_now=yes`.
- Review the remaining diff before committing anything.
- If `README.md` exists and the diff changes behavior, workflow, or
  user-facing expectations, update it before finishing.
- If `CHANGELOG.md` exists and the diff changes behavior or workflow, add an
  unreleased entry before finishing.
- If `VERSION` exists, only bump it when warranted:
  - no bump for docs-only or non-behavioral cleanup
  - patch for fixes or behavior corrections
  - minor for new user-visible capability
  - major only for intentional breaking contract changes
- Commit all non-ignored remaining artifacts in the source worktree before the
  final merge step.
- If merging local `main` into the source worktree conflicts, resolve the
  conflicts in the source worktree immediately, commit the resolution there,
  and continue the finish flow instead of stopping for user intervention.
- Run `$HOME/.agents/skills/merge-worktree/scripts/finalize_worktree.sh finish --target-branch main`
  only after `inspect` reports `can_finish_now=yes` and the source worktree is
  clean and committed.

## Finish contract

- `finish` merges local `main` into the source worktree only when the source
  worktree does not already contain the current local `main` tip.
- If that merge conflicts, resolve the conflicts in the source worktree,
  commit the result there, and rerun `finish`.
- `finish` updates local `main` with a fast-forward-only merge.
- `finish` leaves the source worktree in place after the fast-forward into
  local `main` succeeds.
- Codex/Desktop owns any later worktree cleanup.

## Failure behavior

- If the target `main` worktree is dirty but its dirty paths do not overlap the
  incoming source-worktree changes, continue.
- If the target `main` worktree has dirty paths that overlap the incoming
  source-worktree changes, stop and report the conflicting paths.
- If merging local `main` into the source worktree conflicts, leave the source
  worktree in place, resolve the conflicts there, commit the resolution, and
  rerun `finish`.
- If fast-forwarding local `main` fails, stop and leave the source worktree in
  place.
- Do not fetch, push, or reconcile against `origin/main`.
