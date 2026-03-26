# Specification: Fix Nix Profile Symlink

## Overview
The `.nix-profile` symlink in the user's home directory is pointing to a non-existent standard Nix profile path (`~/.local/state/nix/profiles/profile`) instead of the Home Manager managed profile. This track ensures that `.nix-profile` is correctly managed by Home Manager and points to the active Home Manager generation.

## Functional Requirements
- **Align Symlink**: Update the Home Manager configuration to explicitly manage the `~/.nix-profile` symlink.
- **Point to Home Manager**: The symlink should point to `~/.local/state/nix/profiles/home-manager`.
- **Clean Up**: Ensure any broken or incorrect legacy symlinks are removed or overwritten during the Home Manager activation.

## Acceptance Criteria
- [ ] `~/.nix-profile` exists and is a symlink.
- [ ] `~/.nix-profile` points to `~/.local/state/nix/profiles/home-manager`.
- [ ] The Home Manager profile itself correctly points to the current HM generation in the Nix store.

## Out of Scope
- Migrating non-NixOS legacy profiles.
- Managing system-wide profiles (handled by NixOS).
