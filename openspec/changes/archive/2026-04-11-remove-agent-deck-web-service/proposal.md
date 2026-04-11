## Why

The repo currently treats the WSL `agent-deck web` user service as a supported default for the `nixos` user, but that background UI is no longer wanted. We should remove the declarative startup path and its documented support while keeping `agent-deck` itself available as managed interactive tooling on develop hosts.

## What Changes

- **BREAKING** Remove the repo-managed WSL `agent-deck web` startup path for the `nixos` user from the Home Manager WSL profile.
- Remove the active documentation and agent memory statements that describe `agent-deck web` as an automatically started supported service on WSL develop hosts.
- Remove or update the active OpenSpec requirement that currently defines the WSL `agent-deck web` user-service contract.
- Keep the repo-managed `agent-deck` package and `agent-deck-launch` helper installed through the develop Home Manager profile.
- Document that any remaining live user-level `agent-deck web` artifacts are cleaned up manually after the config change is applied.

## Capabilities

### New Capabilities

### Modified Capabilities
- `develop-agent-deck-web-startup`: Remove the requirement that WSL develop hosts define, verify, and document an automatic `agent-deck web` user service.
- `develop-agent-deck-packaging`: Clarify that `agent-deck` remains a managed develop-host tool even though the background WSL web service support is removed.

## Impact

- Affected code: WSL Home Manager profile wiring, active documentation, changelog text, AGENTS memory, and the active OpenSpec spec for `develop-agent-deck-web-startup`.
- Affected systems: WSL develop hosts and repo-only workflow/spec files; no server-host service behavior changes are intended.
- Activation/manual cleanup: after the updated config is applied, any remaining generated user unit files, enablement symlinks, running tmux session, and `~/.agent-deck/web-service.log` cleanup stays manual.
