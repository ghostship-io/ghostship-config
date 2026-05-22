---
name: ghostship-pull-worktree
description: Create and prepare a pull request from the current Ghostship worktree. Use when asked to open a PR, create a draft PR, request Codex review, address Codex review feedback, fix CI failures, and leave the PR ready to merge. Do not use for normal implementation work.
---

# Ghostship Pull Worktree

Create and prepare a pull request from the current worktree.

Operate on the current worktree only.

## Goals

- Ensure the worktree changes are on a branch.
- Push the branch.
- Create a draft pull request with `gh`.
- Request Codex review from the pull request body.
- Wait for Codex review to complete.
- Address all Codex review issues.
- Wait for CI to pass.
- Fix CI failures.
- Mark the pull request ready to merge only after Codex review issues are
  addressed and CI passes.
- Return the pull request URL and final status to the user.

## Rules

- Do not merge the pull request unless explicitly instructed.
- Do not mark the pull request ready while Codex review issues remain.
- Do not mark the pull request ready while CI is failing or still pending.
- Do not ignore Codex review comments.
- Do not ignore failing required checks.
- Do not include unrelated worktree changes.
- Do not create new tooling unless explicitly asked.
- Prefer the installed GitHub plugin skills for detailed GitHub operations when
  they are available; use `gh` for command-line gaps and required PR actions.

## Process

1. Inspect the worktree:
   - Check `git status`.
   - Confirm the repo has a `main` branch or `origin/main`.
   - Confirm `gh` is installed and authenticated.
   - Confirm the current worktree has changes or commits to submit.

2. Ensure a branch exists:
   - If already on a non-`main` branch, use the current branch.
   - If on `main`, `master`, or detached HEAD, create a new branch for the PR.
   - Use a concise branch name based on the work performed.
   - Do not overwrite an existing branch unless explicitly instructed.

3. Prepare the branch:
   - Include only relevant worktree changes.
   - Commit uncommitted changes if needed.
   - Push the branch to the remote.

4. Create the pull request:
   - Use `gh pr create --draft`.
   - Set the base branch to `main` unless the repo clearly uses a different
     default branch.
   - Include a concise title and body.
   - The PR body must request Codex review directly with:

     `@codex review`

5. Wait for Codex review:
   - Monitor the pull request until Codex review completes.
   - Check GitHub PR reviews, review comments, PR comments, and check output
     related to Codex.
   - If both automatic Codex review and the explicit `@codex review` produce
     feedback, address both.

6. Address Codex feedback:
   - Fix every concrete issue raised by Codex.
   - Commit and push fixes to the same branch.
   - Re-check the pull request for remaining Codex comments.
   - Repeat until Codex review has no unresolved issues.

7. Wait for CI:
   - Monitor pull request checks.
   - If CI fails, inspect the failing logs.
   - Fix the failure.
   - Commit and push fixes to the same branch.
   - Repeat until CI passes.

8. Mark ready:
   - Only after all Codex review issues are addressed and CI passes, run
     `gh pr ready`.
   - Do not merge the pull request unless explicitly instructed.

## Output

Use normal Codex output.

Include:

- PR URL
- branch name
- base branch
- whether Codex review completed
- whether all Codex issues were addressed
- CI status
- whether the PR was marked ready
- any remaining blockers

If the PR cannot be completed, return the blocker and the current PR URL if one
exists.
