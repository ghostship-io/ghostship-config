---
name: ghostship-review-worktree
description: Thoroughly review changes made during the current Codex session. Use when asked to review session work, inspect recent Codex changes, find concrete issues, or create a plan for security, leaked secrets, correctness, performance, consistency, documentation, README, tests, or bloat problems. Do not use for merge preparation, PR creation, or normal implementation work.
---

# Ghostship Review Worktree

Thoroughly review the work completed during the current Codex session.

Operate as a reviewer and planner. Do not edit files unless explicitly asked.

## Scope

Focus only on changes made during the current Codex session.

Use available session and repository context to identify the reviewed changes, including:

- current conversation/session context
- `git status`
- staged changes
- unstaged changes
- untracked files created during the session
- commits created during the session
- relevant nearby code needed to understand the changes
- call sites, callers, and downstream usage affected by the changes

Do not fetch, update, merge, rebase, or compare against `main` as part of this review.

Do not review merge readiness, base drift, branch freshness, or conflict risk. Those belong to merge or pull request workflows.

Do not review the entire repository blindly, but follow the changed code far enough to validate behavior, integration, and consistency.

## Review depth

Be thorough.

Inspect:

- the full set of session changes
- surrounding code for each changed area
- existing project patterns for similar behavior
- tests that cover or should cover the change
- configuration and environment assumptions
- API, CLI, data model, schema, migration, or contract changes
- error handling and logging paths
- security boundaries and trust boundaries
- performance-sensitive paths
- documentation affected by behavior, setup, configuration, or workflow changes

Do not stop at superficial style comments. Prioritize concrete issues that could affect correctness, security, maintainability, operability, or user behavior.

## Review goals

Find concrete, actionable issues in the session changes.

Check for:

- security vulnerabilities
- leaked credentials, tokens, keys, secrets, or sensitive fixtures
- correctness bugs
- broken edge cases
- unsafe input handling or missing validation
- authorization, authentication, or permission mistakes
- data loss, migration, serialization, or compatibility risks
- concurrency, ordering, caching, or lifecycle bugs
- performance regressions
- unnecessary expensive work
- inconsistent APIs, naming, error handling, logging, tests, configuration, or architecture
- incomplete or missing tests for changed behavior
- brittle tests or tests that do not verify the intended behavior
- missing or outdated `README.md` updates when behavior, usage, setup, configuration, commands, environment variables, or user-facing functionality changed
- missing or outdated docs updates when project documentation is affected
- stale examples, comments, or usage instructions caused by the change
- unnecessary bloat, dead code, speculative abstractions, or unrelated changes

Do not review `CHANGELOG.md` or version bumps as part of this skill.

Do not invent theoretical issues. If a risk is speculative, label it as speculative or omit it.

## Documentation review

Review documentation impact explicitly.

Check whether the session changes require updates to:

- `README.md`
- docs directories
- setup or install instructions
- CLI or API usage examples
- configuration references
- environment variable documentation
- troubleshooting notes
- architecture or workflow docs
- generated docs only if the repo already uses them

Recommend documentation updates only when the code changes affect documented behavior, setup, operation, configuration, or user-facing workflows.

## Checks

Run relevant repo-local checks when appropriate and available, such as:

- tests related to changed files
- broader tests when changed code has wide impact
- lint
- typecheck
- build
- formatting checks
- configured secret scanning
- documentation validation if configured

Do not add new tooling.

## Output

Use normal Codex plan-mode output.

Include:

- what session changes were reviewed
- checks run and results
- concrete findings with file and line references where possible
- severity for each finding when useful
- evidence for each finding
- fix plan for each issue
- documentation and `README.md` review result
- recommended fix order
- verification steps to run after fixes
- remaining uncertainty or blockers, if any

If no concrete issues are found, say so directly and list the checks performed.
