# Specification: Update NixOS to 25.11

## Overview
Update the NixOS configuration repository from version 24.11 to 25.11. This includes updating `nixpkgs` and `home-manager` inputs in `flake.nix`, and addressing any resulting configuration changes or deprecations.

## Functional Requirements
- **Update Flake Inputs**: Update `nixpkgs` and `home-manager` inputs in `flake.nix` to point to the `nixos-25.11` and `release-25.11` branches respectively.
- **Update Home Manager State Version**: Increment `home.stateVersion` in `home/nixos.nix` to `25.11`.
- **Address Deprecations**: Identify and fix any configuration options that have been deprecated or removed in the new release.

## Non-Functional Requirements
- **System Stability**: The update must result in a bootable and functional system.
- **Minimal Downtime**: The transition should be smooth with clear verification steps.

## Acceptance Criteria
- [ ] `flake.nix` points to NixOS 25.11 channels.
- [ ] System rebuilds successfully without errors.
- [ ] Home Manager environment activates correctly.
- [ ] Critical services (SSH, shell, etc.) remain functional.

## Out of Scope
- Major architectural refactoring unrelated to the version update.
- Switching to `unstable` branch.