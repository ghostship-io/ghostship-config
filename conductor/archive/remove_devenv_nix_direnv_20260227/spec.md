# Specification: Replace direnv with nix-direnv and Remove devenv/cachix

## Overview
Decommission the `devenv` development tool and its associated binary cache (`cachix`) from the NixOS configuration. Simultaneously, transition the development environment management from standard `direnv` to `nix-direnv` to ensure better performance and seamless Nix integration.

## Functional Requirements
- **Removal of devenv/cachix**:
  - Remove `devenv` from `environment.systemPackages` in `modules/common/default.nix`.
  - Remove the `devenv.cachix.org` substituter and trusted public key from `nix.extraOptions` in `modules/common/default.nix`.
  - Remove `devenv` from user-level packages in `home/nixos.nix` (or equivalent).
- **Transition to nix-direnv**:
  - Ensure `programs.direnv.nix-direnv.enable = true` is set in the appropriate configuration (NixOS or Home Manager).
  - Explicitly use `nix-direnv` instead of standard `direnv` in system packages.
  - Verify that `nix-direnv` is correctly installed and integrated into the Fish shell.
- **Documentation Update**:
  - Remove `devenv` from the `tech-stack.md` document.
  - Update any relevant sections in `README.md` if they mention `devenv`.

## Functional Constraints
- The removal should not affect other system utilities or core Nix settings.
- `nix-direnv` must remain functional after the removal of `devenv`.

## Acceptance Criteria
- [ ] `devenv` command is no longer available in the shell.
- [ ] `grep devenv /etc/nix/nix.conf` returns no results.
- [ ] `direnv` is configured with `nix-direnv` enabled.
- [ ] `tech-stack.md` no longer references `devenv`.

## Out of Scope
- Migrating existing `devenv.nix` files to pure Nix or other formats.
- Removing other binary caches not related to `devenv`.
