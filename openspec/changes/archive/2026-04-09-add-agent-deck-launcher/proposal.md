## Why

Starting `agent-deck` from the current repo still requires repetitive manual setup: creating or reusing the matching group, choosing the tool, and inventing a session title. The current naming mismatch between the upstream `gemini-cli` package name and this repo's exposed `gemini` command also adds friction for shell use and for any launcher that wants to accept common agent names directly.

## What Changes

- Add a repo-managed `agent-deck-launch` helper for develop hosts that launches the current directory into `agent-deck`.
- Make the helper ensure a group matching the current directory name exists before launch, creating it when missing.
- Make the helper default to `codex` but accept an optional positional agent parameter such as `gemini-cli`, `gemini`, `opencode`, or another explicit command name.
- Generate `agent-deck` session titles in `YYYY-MM-DD-N` format, where `N` increases dynamically from Agent Deck's current JSON-visible sessions for the current project on that date.
- Expose `gemini-cli` as a shell-wide develop-host command that behaves the same as the existing managed `gemini` wrapper.
- Update active documentation and changelog entries to describe the new launcher workflow and the added `gemini-cli` command surface.

## Capabilities

### New Capabilities
- `agent-deck-project-launcher`: Provide a managed helper that prepares the current project group and launches `agent-deck` sessions with consistent tool selection and date-based titles.

### Modified Capabilities
- `agent-launcher-defaults`: Extend the managed develop-host Gemini launcher surface so `gemini-cli` works everywhere in the shell with the same behavior as `gemini`.

## Impact

- Affected systems: develop hosts only, across both Home Manager interactive tooling and develop-host launcher packaging.
- Affected code: `home/profiles/develop.nix`, `modules/develop/gemini-wrapper.nix`, and possibly a new local helper package or script source.
- Manual implications: the new commands will not exist until the relevant NixOS rebuild or Home Manager switch is applied.
- Documentation: `README.md`, `CHANGELOG.md`, and `AGENTS.md` need updates because the supported develop-host agent workflow changes.
