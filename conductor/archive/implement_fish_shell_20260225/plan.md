# Implementation Plan: Implement Fish Shell for nixos User

## Phase 1: Core Fish & Package Setup
- [x] Task: Enable `fish` shell for the `nixos` user (not root).
    - [x] Update `modules/common/user-nixos.nix` to enable `programs.fish.enable = true;`.
    - [x] Set `users.users.nixos.shell = pkgs.fish;`.
    - [x] Ensure `root` shell remains `bash` (default).
- [x] Task: Update `home/nixos.nix` to include ported packages.
    - [x] Add `p7zip`, `bat`, `cifs-utils`, `fastfetch`, `fd`, `git-lfs`, `ldns`, `python3Packages.pipx`, `ripgrep-all`, `zoxide`, `nodejs`, `starship`.
    - [x] Remove `lsd` as per user request.
- [x] Task: Silence Nix evaluation and dirty tree warnings.
    - [x] Add `warn-dirty = false` to `modules/common/default.nix`.
    - [x] Add `nixpkgs.config.allowAliases = false` to `modules/common/default.nix`.
- [x] Task: Conductor - User Manual Verification 'Core Fish & Package Setup' (Protocol in workflow.md)

## Phase 2: Fish Configuration & Plugins
- [~] Task: Configure `fish` in Home Manager (`home/nixos.nix`).
    - [ ] Enable `programs.fish.enable = true;`.
    - [ ] Enable `programs.starship.enable = true;`.
    - [ ] Enable `programs.zoxide.enable = true;`.
- [ ] Task: Port Aliases and Functions.
    - [ ] Add `shellAliases` to `programs.fish`.
    - [ ] Add `rmssh` function to `programs.fish.functions`.
- [ ] Task: Manage Fish Plugins.
    - [ ] Research the best way to manage the requested plugins in Home Manager (e.g., `programs.fish.plugins`).
- [ ] Task: Conductor - User Manual Verification 'Fish Configuration & Plugins' (Protocol in workflow.md)

## Phase 3: Separate Gemini CLI Management
- [ ] Task: Create a mechanism for `gemini` command.
    - [ ] Option A: Create a Nix derivation for `gemini-cli`.
    - [ ] Option B: Create a separate activation script or module for it.
- [ ] Task: Conductor - User Manual Verification 'Separate Gemini CLI Management' (Protocol in workflow.md)
