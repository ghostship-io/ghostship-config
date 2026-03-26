# Implementation Plan: WSL-Specific Common Settings

## Phase 1: Shared WSL Logic
- [x] Task: Refactor `modules/common/default.nix` (f776541) to remove global `systemd-networkd`
- [x] Task: Create `modules/common/wsl.nix` (39d7fee) with DNS and networking tweaks
- [x] Task: Import `modules/common/wsl.nix` (51b7a2e) in `hosts/launch-octopus/default.nix`
- [x] Task: Update `conductor/product-guidelines.md` with WSL architecture notes (2081b2e)
- [x] Task: Conductor - User Manual Verification 'Phase 1: WSL Shared Logic' (Protocol in workflow.md)
