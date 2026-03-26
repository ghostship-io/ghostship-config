# Implementation Plan: Replace direnv with nix-direnv and Remove devenv/cachix

## Phase 1: Removal and Cleanup [checkpoint: 050f994]
- [x] Task: Remove `devenv` and `cachix` substituters from `modules/common/default.nix`. 42236b8
- [x] Task: Remove `devenv` from `home/nixos.nix` (Home Manager packages). d71d518
- [x] Task: Remove `devenv` from `tech-stack.md`. 5735df0
- [x] Task: Conductor - User Manual Verification 'Phase 1: Removal and Cleanup' (Protocol in workflow.md)

## Phase 2: nix-direnv Transition [checkpoint: 5bedf39]
- [x] Task: Enable `nix-direnv` in the system configuration (e.g., `programs.direnv.nix-direnv.enable = true`). 0474f75
- [x] Task: Verify that `direnv` and `nix-direnv` are correctly configured for the Fish shell. 8e1281a
- [x] Task: Conductor - User Manual Verification 'Phase 2: nix-direnv Transition' (Protocol in workflow.md)

## Phase 3: Final Verification [checkpoint: 8bbe837]
- [x] Task: Apply configuration with `sudo nixos-rebuild switch --flake .#launch-octopus`. manual
- [x] Task: Verify `devenv` is gone and `nix-direnv` is working. manual
- [x] Task: Conductor - User Manual Verification 'Phase 3: Final Verification' (Protocol in workflow.md)
