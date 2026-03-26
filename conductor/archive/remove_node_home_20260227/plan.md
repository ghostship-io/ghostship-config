# Implementation Plan: Remove global Node.js from User Environment

## Phase 1: Implementation [checkpoint: ab28426]

- [x] Task: Remove `nodejs` from `home.packages` in `home/nixos.nix`. 73269a7
- [x] Task: Conductor - User Manual Verification 'Phase 1: Implementation' (Protocol in workflow.md)

## Phase 2: Verification [checkpoint: cef5100]

- [x] Task: System Apply and Test a6563af
    - [x] Run `sudo nixos-rebuild switch --flake .#launch-octopus`.
    - [x] Run `node --version` and ensure it's not found globally.
    - [x] Run `gemini --help` to ensure the Gemini CLI still works via its internal Node.js.
    - [x] Run `inshellisense --help` to ensure Node.js-based system tools remain functional.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Verification' (Protocol in workflow.md)
