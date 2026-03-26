# Track: armored_armadillo_20260310 Specification

## Overview
Add a new NixOS host configuration named `armored-armadillo`. This host is a WSL2 environment intended for use on a desktop workstation. It should be functionally identical to the existing `launch-octopus` host (which is used on a laptop), sharing the same system modules, Home Manager configuration, secrets, and WSL2 integration features.

## Functional Requirements
- Define a new host entry `armored-armadillo` in `flake.nix`.
- Create a dedicated directory `hosts/armored-armadillo/`.
- Reuse existing shared modules for WSL2 (`modules/wsl/`), user configuration (`modules/common/user-nixos.nix`, `modules/common/users.nix`), and secrets.
- Enable full WSL2-to-Windows integration:
    - Windows notifications.
    - File sharing and system time synchronization.
    - SSH agent/keychain sharing.
- Ensure `armored-armadillo` and `launch-octopus` stay in sync by utilizing the same module imports.

## Non-Functional Requirements
- **Consistency**: The environment on `armored-armadillo` must match `launch-octopus` to provide a seamless transition between desktop and laptop.
- **Maintainability**: Use modular imports to avoid duplication.

## Acceptance Criteria
- [ ] `nixos-rebuild build --flake .#armored-armadillo` completes successfully.
- [ ] `hosts/armored-armadillo/default.nix` exists and imports the necessary modules.
- [ ] `armored-armadillo` is present in `flake.nix` outputs.
- [ ] Home Manager configuration for the `nixos` user is applied correctly on the new host.

## Out of Scope
- Any hardware-specific optimizations for non-WSL2 environments.
- Unique application configurations specific only to the desktop.
