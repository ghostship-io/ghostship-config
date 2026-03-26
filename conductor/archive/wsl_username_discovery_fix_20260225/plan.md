# Implementation Plan: WSL Username Discovery Fix

## Phase 1: Update Discovery Logic [checkpoint: e26d7d7]

- [x] Task: Update PowerShell command in `modules/common/wsl.nix` to use `$env:UserName`. b9ba383
    - [x] Modify the `system.activationScripts.wslHomeSymlink` block. b9ba383
    - [x] Update variable assignment to use `tr -d '\r'` as specified. b9ba383
- [x] Task: Update the path construction for Windows user profile. b9ba383
    - [x] Use `/mnt/c/Users/<WIN_USER>` as the primary path for discovery. b9ba383
- [x] Task: Verify the changes. ffcfc75
    - [x] Ensure `tr -d '\r'` is used for cleaning PowerShell output. ffcfc75
- [x] Task: Conductor - User Manual Verification 'Phase 1: Update Discovery Logic' (Protocol in workflow.md) e26d7d7

## Phase 2: Testing and Checkpointing [checkpoint: 7ad0064]

- [x] Task: Test the activation script (if possible to run it manually or verify via system rebuild). 7ad0064
- [x] Task: Verify the symlink `~/win-home` exists and points to the correct Windows user directory. 7ad0064
- [x] Task: Conductor - User Manual Verification 'Phase 2: Testing and Checkpointing' (Protocol in workflow.md) 7ad0064
