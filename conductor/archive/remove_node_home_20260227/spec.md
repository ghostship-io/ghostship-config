# Specification: Remove global Node.js from User Environment

## Overview
Decommission Node.js from the global user environment (`home.packages`) to maintain a lean base system. Transition Node.js development to a per-project `nix-direnv` approach, while ensuring that system tools (like the Gemini CLI) that internally depend on Node.js remain functional.

## Functional Requirements
- **Global Package Removal**: Remove `nodejs` from the `home.packages` list in `home/nixos.nix`.
- **System Tool Stability**: Ensure that the `gemini` command (defined in `modules/common/gemini.nix`) remains functional by continuing to use its internal reference to `${pkgs.nodejs}`.
- **Workflow Transition**: Documentation update or confirmation that future Node.js development should use project-specific flakes or `nix-shell` via `direnv`.

## Functional Constraints
- Node.js should not be available in the global `PATH` after removal.
- Tools explicitly referencing `pkgs.nodejs` in the Nix configuration will continue to work.

## Acceptance Criteria
- [ ] `nodejs` is removed from `home/nixos.nix`.
- [ ] Running `node --version` in a fresh shell (without an active nix-shell/direnv) fails.
- [ ] Running `gemini --version` (or similar) succeeds.
- [ ] `sudo nixos-rebuild switch --flake .#launch-octopus` succeeds.

## Out of Scope
- Migrating existing Node.js projects to Nix-native environments.
- Removing Node.js from the Nix store (it will remain as a dependency for tools like Gemini).
