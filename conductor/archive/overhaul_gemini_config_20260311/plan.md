# Implementation Plan: Overhaul Gemini CLI & Module Refactor

## Phase 1: Module Refactoring [checkpoint: 54fd4bd]
- [x] Task: Rename `modules/wsl/` to `modules/develop/` [1a203fb]
- [x] Task: Move `modules/common/gemini.nix` to `modules/develop/gemini.nix` [9a98383]
- [x] Task: Update `flake.nix` and host imports to reflect the new `develop` path [f6d1e44]
- [x] Task: Conductor - User Manual Verification 'Module Refactoring' (Protocol in workflow.md) [54fd4bd]

## Phase 2: Gemini Instruction Overhaul [checkpoint: 88e5efa]
- [x] Task: Distill instructions from `home/config/skills/system.md` into a new global `gemini.md` [2146b7a]
- [x] Task: Integrate `gemini.md` into Home Manager (`home.file` in `home/nixos.nix`) [9e19b9a]
- [x] Task: Remove `system` skill from `modules/develop/gemini.nix` (`settings.json`) [64ec62c]
- [x] Task: Update `gemini.md` with Conductor manual validation emphasis [910f033]
- [x] Task: Remove Hyper-V references from `gemini.md` [0e2925d]
- [x] Task: Delete the `home/config/skills/system.md`, `python.md`, `hyper-v.md`, and `hyper-v-console.ps1` files [e905d0d]
- [x] Task: Conductor - User Manual Verification 'Gemini Instruction Overhaul' (Protocol in workflow.md) [88e5efa]

## Phase 3: Final Verification and Cleanup [checkpoint: 51c8570]
- [x] Task: Run `nh os build` and `nh os switch` to verify the new configuration [53ce17c]
- [x] Task: Verify that Gemini CLI correctly loads the global user `gemini.md` [53ce17c]
- [x] Task: Perform a final cleanup of any unused configuration fragments [53ce17c]
- [x] Task: Conductor - User Manual Verification 'Final Verification and Cleanup' (Protocol in workflow.md) [51c8570]
