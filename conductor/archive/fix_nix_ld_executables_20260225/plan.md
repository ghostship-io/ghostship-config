# Implementation Plan: Fix NixOS Dynamic Executables

## Phase 1: Enable nix-ld [checkpoint: 85a4836]
- [x] Task: Enable nix-ld in common configuration 85a4836
- [x] Task: Rebuild and Verify 85a4836
    - [x] Run `sudo nixos-rebuild switch --flake .#launch-octopus` (or relevant host).
    - [x] Verify `code .` starts.
