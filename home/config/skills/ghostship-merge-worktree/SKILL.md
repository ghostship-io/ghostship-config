---
name: ghostship-merge-worktree
description: Merge the current worktree branch back into main. Use when asked to prepare a worktree for merge, update main, merge main into the worktree, resolve drift or conflicts, merge the branch into main, verify main is clean, and push main to origin. Do not use for pull request workflows.
---

# Ghostship Merge Worktree

Merge the current worktree branch back into `main`.

This skill is for direct local merge workflows, not pull request workflows.

## Goals

- Ensure the current worktree changes are on a branch.
- Update `main` from `origin/main` when possible.
- Compare the worktree branch against updated `main`.
- Merge updated `main` into the worktree branch.
- Resolve conflicts and align the worktree with current `main`.
- Merge the worktree branch back into `main`.
- Ensure `main` is clean after merge.
- Push `main` to `origin` if possible.

## Rules

- Do not merge unrelated changes.
- Do not discard user changes unless explicitly instructed.
- Do not force-push.
- Do not merge into `main` while tests or required checks are clearly failing.
- Do not leave unresolved conflicts.
- Do not leave `main` dirty.
- If a conflict cannot be resolved safely, stop and report the blocker.
- Use `ghostship-pull-worktree` instead when the requested path is a pull
  request workflow.

## Process

1. Inspect the current worktree:
   - Run `git status`.
   - Identify the current branch.
   - Identify staged, unstaged, and untracked changes.
   - Confirm the repo has `main` or `origin/main`.

2. Ensure the worktree is on a branch:
   - If already on a non-`main` branch, use the current branch as the worktree
     branch.
   - If on `main`, create a new branch for the current worktree changes before
     merging.
   - If on detached HEAD, create a branch before continuing.
   - Do not overwrite an existing branch unless explicitly instructed.

3. Preserve worktree changes:
   - Commit relevant staged and unstaged changes if needed.
   - Do not include unrelated files.
   - Leave unrelated or uncertain files untouched and report them as blockers
     if they prevent a safe merge.

4. Update `main`:
   - Fetch `origin/main` if network access is available.
   - If local `main` is behind `origin/main`, update local `main` from
     `origin/main`.
   - If `main` is checked out in another worktree, update it from that worktree
     when possible.
   - If local `main` cannot be updated, use the freshest available
     main-equivalent ref and report the limitation.

5. Compare against `main`:
   - Compare the worktree branch with updated `main`.
   - Review changed files and the merge base.
   - Note if `main` has drifted significantly since the worktree branch was
     created.

6. Merge `main` into the worktree branch:
   - Merge updated `main` into the worktree branch.
   - Resolve conflicts.
   - Align conflict resolutions with current `main` patterns and behavior.
   - Prefer preserving the worktree's intended changes while adapting them to
     updated `main`.
   - Commit the merge or conflict-resolution changes.

7. Verify the worktree branch:
   - Run relevant repo-local checks when available, such as tests, lint,
     typecheck, build, or formatting checks.
   - If checks fail, fix the failures before merging into `main`.
   - Commit any fixes to the worktree branch.

8. Merge the worktree branch into `main`:
   - Switch to `main`, or operate from the existing `main` worktree if `main`
     is checked out elsewhere.
   - Confirm `main` is up to date with `origin/main`.
   - Merge the worktree branch into `main`.
   - Resolve any remaining conflicts.
   - Do not squash unless explicitly instructed.

9. Verify `main`:
   - Confirm `git status` is clean on `main`.
   - Run relevant final checks if available.
   - If checks fail, fix them on `main` and commit the fixes.
   - Confirm `main` remains clean after fixes.

10. Push:
   - Push `main` to `origin` if remote access is available.
   - Do not force-push.
   - If push fails, report the reason and leave the local merge intact.

## Output

Use normal Codex output.

Include:

- worktree branch name
- main ref used
- whether `main` was updated from `origin/main`
- summary of changes merged
- whether `main` drifted and how it was handled
- conflicts resolved, if any
- checks run and results
- whether `main` is clean
- whether `main` was pushed to `origin`
- any remaining blockers
