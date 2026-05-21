---
name: github-pr-workflow
description: GitHub pull request policy for draft/WIP PRs, automatic Codex review, merge conflict resolution, PR readiness, PR close/merge decisions, and GitHub Actions CI setup or optimization. Use when opening, updating, reviewing, closing, or preparing a GitHub pull request; requesting or handling Codex review; resolving PR feedback or merge conflicts; pushing branches; or configuring GitHub Actions defaults. For local pre-merge worktree review, use ghostship-review-worktree instead.
---

# GitHub PR Workflow

## Overview

Use this skill as the policy layer for GitHub PR work. It should route detailed
GitHub operations to the installed GitHub plugin skills and keep this workspace's
PR and CI defaults consistent.

## Plugin Skill Routing

Prefer the installed GitHub plugin skills for implementation details:

- `github:github`: GitHub triage, repository orientation, PR metadata, labels,
  comments, reactions, and deciding which specialist workflow applies.
- `github:yeet`: staging, committing, pushing, and opening draft PRs.
- `github:gh-address-comments`: unresolved review threads, Codex comments,
  requested changes, inline review locations, and review-thread state.
- `github:gh-fix-ci`: failing GitHub Actions checks, Actions logs, and focused
  CI fixes.

Use local `git` and `gh` for current-branch discovery, branch creation, merge
conflict resolution, Actions logs, and any connector gap.

## PR Lifecycle

- Use a named branch for worktree work.
- Commit and push finished work, then open a PR before returning to the user.
- Open every worktree PR as draft/WIP first. Prefer `github:yeet`; use
  `gh pr create --draft` only as the CLI fallback.
- Treat draft/WIP as the initial validation state only. Keep the PR draft until
  local verification is done, the PR body explains intent, impact, and
  validation, and Codex review feedback has been inspected.
- Ensure the repository is configured for native Codex automatic review through
  the Codex/GitHub integration. Prefer native automatic review over custom
  Codex Action workflows.
- Prefer automatic Codex review when a draft PR is marked ready.
- Request manual Codex review with `@codex review` only when automatic review
  does not run or when major code changes land after review.
- Treat major code changes as production behavior, config, dependencies,
  auth/security, migrations, CI, deployment, or broad refactors.
- Use `github:gh-address-comments` for Codex review feedback and thread state.
- React to Codex review findings with 👍 for useful or accepted feedback and 👎
  for rejected or not-applicable feedback. Prefer connector reactions; fall
  back to the matching GitHub reactions API via `gh api` when needed.
- Resolve merge conflicts locally, push the resolution, and re-check CI and
  Codex review state before calling the PR ready to merge.
- Use `github:gh-fix-ci` for failing GitHub Actions checks.
- Do not call a PR ready while unresolved Codex findings, failing CI, or merge
  conflicts remain.
- Before handing back to the user, mark the PR ready/non-draft when it is ready
  for the user to merge. If a concrete blocker prevents readiness, state it
  explicitly with the PR link and remaining work.
- Merge only after merge conflicts, CI, and Codex feedback are resolved. Leave
  final PR merges to the user when repo policy says so.
- Close abandoned PRs with `gh pr close <pr> --comment ...`; delete branches
  only when clearly intended.

## Repo Setup

- Keep `AGENTS.md` concise and current so Codex review has durable repo
  guidance.
- Verify native automatic Codex review is enabled before relying on it.
- Add a custom Codex Action review workflow only when native automatic review is
  unavailable and the repo explicitly needs one.

## CI Defaults

Apply these across active GitHub Actions workflows unless there is a specific
reason not to:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read
```

Additional defaults:

- Use `retention-days: 3` for uploaded artifacts.
- Use `if: failure()` for noisy integration artifacts.
- Put expensive jobs behind `needs: unit`.
- Add docs-only `paths-ignore` entries for `**/*.md` and `docs/**` where
  appropriate.

Do not invent CI workflows in repositories that do not need them.

## Readiness Checklist

Before marking a PR ready or merge-ready:

- Branch is pushed and tracked.
- Relevant local checks have run or the gap is stated.
- GitHub Actions are passing or pending with a clear reason.
- Automatic Codex review has run, or manual review was requested because it did
  not run or major post-review code changes landed.
- All Codex review findings are fixed or explicitly rejected with rationale and
  reaction.
- Merge conflicts are resolved and the resolution is pushed.
- Draft/WIP state has been cleared unless a concrete blocker is stated.
