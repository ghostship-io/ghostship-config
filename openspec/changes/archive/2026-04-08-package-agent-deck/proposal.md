## Why

`agent-deck` fills a gap in the current develop-host workflow by giving the user a dedicated TUI for coordinating multiple agent sessions across Codex, Gemini, OpenCode, and related tools. Packaging it in this repo keeps installation declarative, reproducible, and aligned with the existing Nix-managed agent tooling instead of relying on an imperative upstream installer.

## What Changes

- Add a repo-managed Nix package for the upstream `agent-deck` CLI from tagged releases.
- Expose `agent-deck` to develop-profile users through Home Manager as interactive tooling rather than a global server-host baseline package.
- Ensure required runtime dependencies for practical use, especially `tmux`, are available on develop hosts where `agent-deck` is installed.
- Document the new packaged workflow and record the change in repo docs and changelog.

## Capabilities

### New Capabilities
- `develop-agent-deck-packaging`: Package and expose `agent-deck` as declarative develop-host tooling in this repo.

### Modified Capabilities

## Impact

- Affected code: develop-profile package wiring, local Nix packaging, and related documentation.
- Affected systems: develop hosts using the shared Home Manager profile; no server-host behavior changes.
- Dependencies: upstream `agent-deck` release source and the local `tmux` runtime dependency.
- Manual implications: users will need a Home Manager or NixOS rebuild/switch before `agent-deck` becomes available in their shell.
