## Why

The current `gh` wiring does two repo-specific things we no longer want: it treats GitHub CLI as part of the shared system baseline, and it injects `/usr/bin/gh` through the WSL `envfs` fallback. We want to return `gh` to ordinary develop-user tooling and remove the repo-managed `envfs` exception for it.

## What Changes

- Move `gh` back into the shared develop Home Manager package list so GitHub CLI is once again categorized as interactive user tooling.
- Remove the explicit WSL `services.envfs` fallback entry that creates `/usr/bin/gh`.
- Update docs to reflect that the repo no longer promises a repo-managed `envfs` path for GitHub CLI and that only the standard user package path remains.

## Capabilities

### New Capabilities
- `develop-github-cli-ownership`: Develop hosts SHALL provide GitHub CLI as develop-profile user tooling without adding a repo-managed `envfs` fallback for `/usr/bin/gh`.

### Modified Capabilities
- None.

## Impact

- Affects develop hosts, WSL develop-host integration, and Home Manager package ownership.
- Removes a repo-managed WSL interoperability path rather than adding a replacement.
- Requires README.md, CHANGELOG.md, and AGENTS.md updates to reflect the narrower GitHub CLI contract.
