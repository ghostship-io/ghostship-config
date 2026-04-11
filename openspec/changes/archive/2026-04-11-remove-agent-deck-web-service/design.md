## Context

The current repo state wires `agent-deck web` into the WSL Home Manager profile as a `systemd --user` service for the `nixos` user and documents that startup path as supported default behavior. The requested change narrows support back down to the interactive `agent-deck` CLI and `agent-deck-launch`, while leaving cleanup of already-generated live user artifacts to a manual post-apply step.

This change crosses configuration, docs, and active OpenSpec requirements, but it does not introduce new architecture or dependencies. The main design question is how to remove the startup contract cleanly without accidentally removing the packaged CLI tooling that develop hosts still need.

## Goals / Non-Goals

**Goals:**
- Remove the declarative WSL `agent-deck web` user-service path from the repo.
- Remove the active docs and spec language that describe automatic WSL web startup as supported behavior.
- Preserve repo-managed `agent-deck` and `agent-deck-launch` availability in the shared develop profile.
- Make the manual cleanup boundary explicit so post-activation live-state cleanup is unambiguous.

**Non-Goals:**
- Removing `agent-deck` itself from the repo-managed develop toolchain.
- Deleting runtime-owned Agent Deck state unrelated to the retired web service.
- Adding a replacement background service, alternate listen address, or shell-init startup path.
- Automating cleanup of already-generated user unit files or live tmux/log artifacts during activation.

## Decisions

### Remove only the WSL-specific service layer
The repo should delete the `agent-deck-web` runner and `systemd.user.services.agent-deck-web` wiring from the WSL Home Manager profile and leave the shared develop profile untouched.

Why:
- The unwanted behavior is isolated to the WSL profile.
- `agent-deck` packaging and `agent-deck-launch` live independently in the develop profile already.
- This keeps the change narrow and avoids regressions to the CLI workflow.

Alternatives considered:
- Remove `agent-deck` entirely: rejected because the requested scope explicitly keeps the tool installed.
- Move the startup path into another profile or shell init: rejected because the user no longer wants a supported background web-service path at all.

### Remove the active startup contract from docs and specs
The repo should update active docs and OpenSpec artifacts so they no longer describe automatic WSL `agent-deck web` startup as supported behavior.

Why:
- Leaving the docs/spec untouched would make the repo contract false after implementation.
- The startup behavior currently exists as both prose and an active spec requirement, so code-only removal would be incomplete.

Alternatives considered:
- Leave the spec as history and only change the config: rejected because `openspec/specs/` represents active requirements, not archive material.

### Keep post-apply live cleanup manual and explicit
The repo should document that cleanup of already-generated user service files, enablement symlinks, tmux sessions, and `~/.agent-deck/web-service.log` happens manually after the config change is applied.

Why:
- The user explicitly wants cleanup after they apply the config manually.
- Removing live user artifacts during activation is riskier than needed for this rollback and mixes desired-state config with one-time state cleanup.

Alternatives considered:
- Add Home Manager activation cleanup for the live artifacts: rejected because it reaches into mutable runtime state the user asked to clean manually.

## Risks / Trade-offs

- [A stale enabled user unit or tmux session survives after config removal] -> Document the exact manual cleanup targets and commands as part of the change.
- [Docs continue to imply the service exists even after config removal] -> Update `README.md`, `CHANGELOG.md`, `AGENTS.md`, and the active OpenSpec delta in the same change.
- [The change accidentally drops `agent-deck` availability entirely] -> Leave `home/profiles/develop.nix` package wiring in place and verify the proposal/specs keep that behavior in scope.

## Migration Plan

1. Remove the WSL-only `agent-deck-web` service wiring from the repo config.
2. Update active docs and OpenSpec specs to match the new supported behavior.
3. Apply the config manually on the target host.
4. Manually stop and disable any remaining `agent-deck-web.service`, remove generated user-unit artifacts, kill the `agent-deck-web` tmux session if it still exists, and delete `~/.agent-deck/web-service.log`.

Rollback would restore the deleted WSL service wiring and revert the related docs/spec changes.

## Open Questions

- None. The requested scope is clear: remove only the background WSL web service, not the packaged `agent-deck` tooling.
