# Implementation Plan: Refactor Gemini CLI Wrapper

## Phase 1: Package Refactoring [checkpoint: a3246fd]

- [x] Task: Update `modules/common/gemini.nix` to use `makeWrapper`. 6e35081
    - [x] Change the `gemini-cli` definition to use `stdenv.mkDerivation` or `symlinkJoin` with `makeWrapper`.
    - [x] Ensure `${pkgs.nodejs}/bin` is prefixed to the script's `PATH`.
    - [x] Ensure `NODE_NO_WARNINGS=1` is exported in the wrapper.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Package Refactoring' (Protocol in workflow.md) a3246fd

## Phase 2: Deployment and Verification [checkpoint: ac5578a]

- [x] Task: Apply configuration. manual
    - [x] Run `sudo nixos-rebuild switch --flake .#launch-octopus`.
- [x] Task: Verify functionality. manual
    - [x] Run `gemini -y` and verify it works without errors.
    - [x] Verify that `node` is still NOT available in the global shell.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Deployment and Verification' (Protocol in workflow.md) ac5578a
