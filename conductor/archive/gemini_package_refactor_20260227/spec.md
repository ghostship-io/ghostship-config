# Specification: Refactor Gemini CLI Wrapper to Bundled Nix Package

## Overview
The `gemini` command currently fails because it depends on `node` being in the global `PATH`, which was removed. This track will refactor the `gemini` wrapper into a proper Nix package that uses `makeWrapper` to bundle `nodejs` into its own execution environment, ensuring it works independently of the global system packages.

## Functional Requirements
- **Bundled Dependency**: Use `makeWrapper` to prefix the `PATH` of the `gemini` script with `${pkgs.nodejs}/bin`.
- **Preserve Logic**: Maintain the existing logic for:
    - Auto-installing the `conductor` extension.
    - Auto-installing the `security` extension.
    - Setting `NODE_NO_WARNINGS=1`.
    - Forwarding all arguments to `@google/gemini-cli` via `npx`.
- **System Integration**: Replace the current `writeShellScriptBin` in `modules/common/gemini.nix` with the new refactored version.

## Non-Functional Requirements
- **Independence**: The `gemini` command must function even if `nodejs` is not present in the user's or system's global packages.
- **Cleanliness**: Use idiomatic Nix patterns for wrapping scripts.

## Acceptance Criteria
- [ ] `gemini` command executes successfully in a shell where `node` is not available.
- [ ] `gemini` correctly triggers extension updates/installs if missing.
- [ ] `sudo nixos-rebuild switch --flake .#launch-octopus` succeeds without errors.

## Out of Scope
- Migrating extensions to pure Nix management (they remain managed via `npx`).
- Changing the Gemini CLI versioning logic.
