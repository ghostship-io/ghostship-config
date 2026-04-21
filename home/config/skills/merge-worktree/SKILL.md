---
name: merge-worktree
description: Finish a Codex Desktop or other git worktree and reconcile it back into local `main`, including detached HEAD worktrees. Use when Claude needs to review and commit outstanding work, best-effort update `README.md` / `CHANGELOG.md` / `VERSION`, merge local `main` into the finished worktree if needed, fast-forward local `main` to the result, and remove the worktree afterward.
---

# merge-worktree

Use this skill to finish a non-`main` worktree and fold it back into local
`main` for personal repositories.

## Core workflow

- Run `scripts/finalize_worktree.sh inspect --target-branch main` from the
  active worktree first.
- Refuse to continue if the active worktree is the `main` worktree or if the
  repo has unresolved merge conflicts.
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
- Run `scripts/finalize_worktree.sh finish --target-branch main` only after the
  source worktree is clean and committed.

## Finish contract

- `finish` creates an ephemeral `codex/finalize-...` branch when the source
  worktree is detached.
- `finish` merges local `main` into the source worktree only when the source
  worktree does not already contain the current local `main` tip.
- If that merge conflicts, resolve the conflicts in the source worktree,
  commit the result there, and rerun `finish`.
- `finish` updates local `main` with a fast-forward-only merge.
- `finish` removes the source worktree only after the fast-forward into local
  `main` succeeds.
- `finish` deletes the ephemeral branch only when it created one.

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
