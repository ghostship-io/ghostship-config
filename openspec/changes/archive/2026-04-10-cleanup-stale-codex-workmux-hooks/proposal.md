## Why

Codex sessions on this host still load a stale `~/.codex/hooks.json` that invokes `workmux`, even though the repo has already removed `workmux` from the supported develop-host toolchain. That leaves Agent Deck and direct Codex sessions failing noisy `UserPromptSubmit` and related hooks with exit code `127`, so the repo should clean up the stale host state and define a durable guard against the same drift recurring.

## What Changes

- Clean up stale Codex hook state that still references removed `workmux` commands.
- Extend the develop-host cleanup contract so removed agent-tool integrations are scrubbed from Codex hook files, not only from the currently tracked `workmux` cache and OpenCode paths.
- Update active documentation and changelog text to describe the stale-hook cleanup behavior and any manual implications for already-running sessions or user-customized hook files.

## Capabilities

### New Capabilities
- `codex-hook-cleanup`: Define how develop hosts detect and remove stale Codex hook commands that reference repo-removed tooling such as `workmux`.

### Modified Capabilities
- `agent-launcher-defaults`: Clarify that the managed Codex workflow should not retain stale removed-tool hook state that causes launch-time hook failures after toolchain changes.

## Impact

- Affected code: develop Home Manager cleanup and activation logic, plus any shared develop-host helper logic that manages Codex runtime state.
- Affected systems: develop hosts and repo workflow documentation; no server-host runtime behavior should change.
- Manual implications: already-running Codex or Agent Deck sessions may still reflect the old hook state until restarted, and any intentionally user-managed custom hook content should be preserved unless it matches the stale removed-tool cleanup rule.
