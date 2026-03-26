# Implementation Plan: WSL2 Features Integration

## Phase 1: WSLENV & Path Integration
- [x] Task: Configure `WSLENV` for `USERPROFILE/p` sharing (38bb7f2)
    - [ ] Add `wsl.wslConf.interop.enabled = true` to common WSL config
    - [ ] Use `wsl.wslConf.automount.enabled = true` (if not already enabled)
    - [ ] Update `modules/common/wsl.nix` with the `WSLENV` setting
- [x] Task: Implement `~/win-home` Symlink Creation (1ab0880)
    - [ ] Create a NixOS activation script to dynamically link `~/win-home` based on the `$USERPROFILE` environment variable.
- [ ] Task: Conductor - User Manual Verification 'WSLENV & Path Integration' (Protocol in workflow.md)

## Phase 2: Explorer & Navigation [checkpoint: 7e0b253]
- [x] Task: Install and Configure `wsl-open` (568dc0a)
    - [x] Add `wsl-open` to `environment.systemPackages` in `modules/common/wsl.nix` (568dc0a)
- [ ] Task: Create `open` Alias (Deferred: To be configured with shell setup)
    - [ ] Update shell configuration (common home-manager or bash/fish) to add `alias open="wsl-open"`
- [x] Task: Conductor - User Manual Verification 'Explorer & Navigation' (Protocol in workflow.md) 7e0b253
