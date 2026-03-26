# Implementation Plan: Refactor WSL-specific Home Manager Configuration

## Phase 1: Configuration Refactoring [checkpoint: d4f48b1]

- [x] Task: Create `home/wsl.nix` with extracted WSL-specific Home Manager logic (ssh-agent, wsl-open, fish init). 02726c5
- [x] Task: Remove WSL-specific logic from `home/nixos.nix` and add a conditional import checking `osConfig.wsl.enable`. 4e156c0
- [x] Task: Conductor - User Manual Verification 'Configuration Refactoring' (Protocol in workflow.md) d4f48b1

## Phase 2: Verification and System Switch [checkpoint: 20d41a0]

- [x] Task: Build the configuration to ensure no syntax or logical errors: `sudo nixos-rebuild build --flake .#launch-octopus`. 7301a42
- [x] Task: Switch to the new configuration on the `launch-octopus` host: `sudo nixos-rebuild switch --flake .#launch-octopus`. fb447a4
- [x] Task: Verify that `open` still works as `wsl-open` in a new Fish session. e022dda
- [x] Task: Verify that `systemctl --user status ssh-agent` is active and `~/.config/ssh-agent.env` is correctly generated. 56ea322
- [x] Task: Conductor - User Manual Verification 'Verification and System Switch' (Protocol in workflow.md) 20d41a0
