## Why

Develop-host agent launchers currently use three different approval models: Gemini explicitly prompts, Codex does not declare a repo default, and OpenCode relies on an upstream permissive default. That leaves the active CLI set inconsistent and hides a risky execution default behind implicit upstream behavior.

## What Changes

- Set explicit YOLO or allow-all execution defaults for Codex, Gemini, and OpenCode through each CLI's supported config surface on develop hosts.
- Make both OpenCode config paths declare `permission = "allow"` so the system and Home Manager variants stay aligned.
- Update active documentation to describe the new develop-host defaults, affected config surfaces, and rebuild or switch requirements.

## Capabilities

### New Capabilities
- `agent-launcher-defaults`: Explicitly define the default approval and sandbox behavior for the repo's active CLI launchers on develop hosts.

### Modified Capabilities
None.

## Impact

- Affects develop hosts and the develop Home Manager profile; it does not change server-host runtime behavior.
- Touches `modules/develop/codex-wrapper.nix`, `modules/develop/gemini.nix`, `modules/develop/opencode-wrapper.nix`, `modules/develop/opencode.nix`, and active workflow documentation.
- Requires a NixOS rebuild on develop hosts for system configs and a Home Manager switch where the Home Manager OpenCode config is used; no manual cleanup is expected.
