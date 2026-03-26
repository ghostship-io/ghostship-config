# Implementation Plan: Refactor Primary User to 'nixos'

## Phase 1: User Migration
- [x] Task: Rename `home/owner.nix` (bf58c69) to `home/nixos.nix` and update content
- [x] Task: Update `hosts/launch-octopus/default.nix` (7d036df) with `nixos` user and group IDs
- [x] Task: Update `flake.nix` (86bd71d) to map `home/nixos.nix` to the `nixos` user
- [x] Task: Update `conductor/product-guidelines.md` (fd4041f) to reflect the `nixos` user standard
- [ ] Task: Conductor - User Manual Verification 'Phase 1: User Migration' (Protocol in workflow.md)
