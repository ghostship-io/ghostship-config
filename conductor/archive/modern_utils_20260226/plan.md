# Implementation Plan: Modern Terminal Utilities Integration

## Phase 1: System-Wide Configuration
- [ ] **Task: Install and Configure fzf**
    - [ ] Add `fzf` to `environment.systemPackages` in `modules/common/default.nix`.
    - [ ] Enable Fish integration for `fzf` in `modules/common/user-nixos.nix` (or `home/nixos.nix` as appropriate for global/user settings).
- [ ] **Task: Conductor - User Manual Verification 'Phase 1: System-Wide Configuration' (Protocol in workflow.md)**

## Phase 2: User-Specific Configuration
- [ ] **Task: Install User Utilities**
    - [ ] Add `duf`, `du-dust`, `procs`, `gping`, `duff`, and `glow` to `home.packages` in `home/nixos.nix`.
- [ ] **Task: Configure Aliases**
    - [ ] Add `df`, `du`, `ps`, and `ping` aliases to `programs.fish.shellAliases` in `home/nixos.nix`.
- [ ] **Task: Conductor - User Manual Verification 'Phase 2: User-Specific Configuration' (Protocol in workflow.md)**

## Phase 3: Final Rebuild and Verification
- [ ] **Task: Apply and Test Configuration**
    - [ ] Run `sudo nixos-rebuild switch --flake .#launch-octopus`.
    - [ ] Verify each new utility and alias in a fresh Fish session.
- [ ] **Task: Conductor - User Manual Verification 'Phase 3: Final Rebuild and Verification' (Protocol in workflow.md)**
