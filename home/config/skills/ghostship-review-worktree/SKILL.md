---
name: ghostship-review-worktree
description: Review the current Ghostship worktree against main before merge. Use when asked to review session changes, inspect a Codex worktree, find concrete issues, or create a fix plan for security, leaked secrets, correctness, performance, consistency, or bloat problems. Do not use for normal implementation work; after approval, use ghostship-merge-worktree for the merge workflow.
---

# Ghostship Review Worktree

Review the current worktree before it is merged.

Operate as a reviewer and planner. Do not edit files unless explicitly asked.

## Scope

Focus on changes made in the current worktree during this session.

Use `main` as the intended merge target.

Before reviewing:

1. Check the current branch and worktree state.
2. Fetch `origin/main` if network access is available.
3. If `origin/main` is ahead of local `main`, update local `main` to match
   `origin/main` only when it is safe to do so.
4. If local `main` cannot be updated because it is checked out elsewhere,
   protected, missing, or the fetch fails, use the freshest available
   main-equivalent ref:
   - prefer `origin/main` if it was fetched successfully
   - otherwise use local `main`
5. Do not merge, rebase, or modify the current worktree branch as part of
   review.

Review the diff from the selected main base to the current worktree, including:

- committed changes in the worktree branch
- staged changes
- uncommitted changes
- relevant nearby code needed to understand the changes

Do not review the entire repository except where needed to validate changed
code against existing patterns.

## Review Goals

Find concrete, actionable issues in the worktree changes.

Check for:

- security vulnerabilities
- leaked credentials, tokens, keys, secrets, or sensitive fixtures
- correctness bugs
- performance regressions
- inconsistencies with existing code patterns, APIs, naming, error handling,
  logging, tests, or configuration
- missing or weak validation
- unnecessary bloat, dead code, speculative abstractions, or unrelated changes

Do not invent theoretical issues. If a risk is speculative, label it as
speculative or omit it.

## Checks

Run relevant repo-local checks when appropriate and available, such as:

- tests related to changed files
- lint
- typecheck
- build
- formatting checks
- configured secret scanning

Do not add new tooling.

## Output

Use normal Codex plan-mode output.

Include:

- selected main base and whether it was refreshed from `origin/main`
- what worktree changes were reviewed
- checks run and results
- concrete findings with file and line references where possible
- a fix plan for each issue
- recommended fix order
- verification steps to run after fixes

If no concrete issues are found, say so directly and list the checks performed.
