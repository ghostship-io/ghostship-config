---
name: ghostship-review-worktree
description: Review the current worktree against the repo's main branch before merge. Use when asked to review session changes, inspect a Codex worktree, find concrete issues, or create a plan for security, leaked secrets, correctness, performance, consistency, documentation, changelog, versioning, or bloat problems. Do not use for normal implementation work.
---

# Ghostship Review Worktree

Review the current worktree before merge.

Operate as a reviewer and planner. Do not edit files unless explicitly asked.

## Scope

Focus on changes made in the current worktree during this session.

Use `main` as the intended merge target.

Before reviewing:

1. Check the current branch and worktree state.
2. Fetch `origin/main` if network access is available.
3. If `origin/main` is ahead of local `main`, update local `main` to match
   `origin/main` when it is safe to do so.
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
- missing or outdated `README.md` updates when behavior, usage, configuration,
  setup, or user-facing functionality changed
- missing, outdated, or unsynced `CHANGELOG.md` updates
- missing or inappropriate version bump
- mismatch between the version number and changelog entry
- unnecessary bloat, dead code, speculative abstractions, or unrelated changes

## Version and Changelog Rules

Always verify that the version is bumped for the worktree changes.

Use the repo's existing version source. Prefer `VERSION` when present. If the
repo uses another canonical version source, such as `package.json`,
`pyproject.toml`, `Cargo.toml`, or similar, use that instead and note it.

The version bump must follow the repo's existing semantic versioning convention:

- `MAJOR` for breaking API, CLI, config, data, migration, or compatibility
  changes
- `MINOR` for backward-compatible features or meaningful user-facing behavior
  changes
- `PATCH` for fixes, refactors, documentation-only changes, test changes,
  tooling changes, performance improvements, and small internal changes
- default to `PATCH` when a bump is required but the correct level is unclear

`CHANGELOG.md` and the version source must be in sync:

- the changelog must include an entry for the new version
- the changelog version must match the bumped version exactly
- the changelog entry must summarize the actual worktree changes
- the changelog must not describe unrelated changes
- if the repo has an existing changelog format, preserve it

Do not invent a new versioning scheme or changelog format.

## Checks

Run relevant repo-local checks when appropriate and available, such as:

- tests related to changed files
- lint
- typecheck
- build
- formatting checks
- configured secret scanning
- documentation or changelog validation if configured
- version consistency checks if configured

Do not add new tooling.

## Output

Use normal Codex plan-mode output.

Include:

- selected main base and whether it was refreshed from `origin/main`
- what worktree changes were reviewed
- checks run and results
- concrete findings with file and line references where possible
- whether `README.md` should be updated
- whether `CHANGELOG.md` is updated and synced
- whether the version is bumped correctly
- the recommended semantic version bump level
- a fix plan for each issue
- recommended fix order
- verification steps to run after fixes

If no concrete issues are found, say so directly and list the checks performed.
